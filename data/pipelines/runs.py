"""Log de ejecución en `reporting.pipeline_runs` (§5.2, §8 y §11.3 del diseño).

Una fila por corrida: se crea en `running` antes de extraer y se cierra en
`completed` o `failed`. Una corrida en `running` cuyo `heartbeat_at` es más viejo
que `stale_minutes` se considera muerta (proceso caído) y se marca `failed` con
`error_type = 'stale_run'`, para que nunca bloquee el pipeline para siempre.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine


PIPELINE_NAME = "weekly_warehouse_client_performance"
RUNS_LOCK_KEY = f"{PIPELINE_NAME}:runs"
ERROR_MESSAGE_MAX_LENGTH = 500

RUN_COLUMNS = (
    "run_id",
    "pipeline_name",
    "trigger",
    "triggered_by",
    "prefect_flow_run_id",
    "status",
    "last_completed_phase",
    "window_start",
    "window_end",
    "started_at",
    "heartbeat_at",
    "finished_at",
    "loaded_at",
    "duration_ms",
    "events_extracted",
    "duplicates_dropped",
    "events_excluded",
    "events_rejected",
    "events_by_type",
    "rows_inserted",
    "rows_updated",
    "rows_unchanged",
    "rows_deleted",
    "source_max_timestamp",
    "capture_coverage",
    "warnings",
    "error_type",
    "error_message",
)

LOCK_SQL = "select pg_advisory_xact_lock(hashtext(:lock_key))"

CLOSE_STALE_SQL = """
update reporting.pipeline_runs
set status = 'failed',
    finished_at = now(),
    error_type = 'stale_run',
    error_message = 'Corrida sin heartbeat: el proceso terminó sin cerrar la corrida.'
where pipeline_name = :pipeline_name
  and status = 'running'
  and heartbeat_at < now() - make_interval(mins => :stale_minutes)
"""

ACTIVE_RUN_SQL = """
select run_id
from reporting.pipeline_runs
where pipeline_name = :pipeline_name
  and status = 'running'
  and heartbeat_at >= now() - make_interval(mins => :stale_minutes)
order by started_at desc
limit 1
"""

INSERT_RUN_SQL = """
insert into reporting.pipeline_runs
  (run_id, pipeline_name, trigger, triggered_by, prefect_flow_run_id, status,
   window_start, window_end)
values
  (:run_id, :pipeline_name, :trigger, :triggered_by, :prefect_flow_run_id, 'running',
   :window_start, :window_end)
"""

HEARTBEAT_SQL = """
update reporting.pipeline_runs
set heartbeat_at = now(),
    last_completed_phase = :phase,
    events_extracted = coalesce(:events_extracted, events_extracted),
    duplicates_dropped = coalesce(:duplicates_dropped, duplicates_dropped),
    events_excluded = coalesce(:events_excluded, events_excluded),
    events_rejected = coalesce(:events_rejected, events_rejected),
    events_by_type = coalesce(cast(:events_by_type as jsonb), events_by_type),
    source_max_timestamp = coalesce(:source_max_timestamp, source_max_timestamp)
where run_id = :run_id
"""

CLOSE_RUN_SQL = """
update reporting.pipeline_runs
set status = :status,
    finished_at = now(),
    heartbeat_at = now(),
    duration_ms = cast(extract(epoch from (now() - started_at)) * 1000 as integer),
    capture_coverage = coalesce(cast(:capture_coverage as jsonb), capture_coverage),
    warnings = cast(:warnings as jsonb),
    error_type = :error_type,
    error_message = :error_message
where run_id = :run_id
"""

LATEST_RUN_SQL = f"""
select {", ".join(RUN_COLUMNS)}
from reporting.pipeline_runs
where pipeline_name = :pipeline_name
order by started_at desc
limit 1
"""


@dataclass(frozen=True)
class OpenRunResult:
    opened: bool
    run_id: UUID
    active_run_id: UUID | None = None
    stale_runs_closed: int = 0


def _json_or_none(value: Any) -> str | None:
    return None if value is None else json.dumps(value, default=str)


def open_run(
    engine: Engine,
    *,
    run_id: UUID,
    trigger: str,
    triggered_by: str | None,
    window_start: date,
    window_end: date,
    prefect_flow_run_id: UUID | None,
    stale_minutes: int,
) -> OpenRunResult:
    """Crea la fila `running` salvo que ya haya otra corrida viva."""
    with engine.begin() as connection:
        connection.execute(text(LOCK_SQL), {"lock_key": RUNS_LOCK_KEY})
        stale = connection.execute(
            text(CLOSE_STALE_SQL),
            {"pipeline_name": PIPELINE_NAME, "stale_minutes": stale_minutes},
        ).rowcount
        active = connection.execute(
            text(ACTIVE_RUN_SQL),
            {"pipeline_name": PIPELINE_NAME, "stale_minutes": stale_minutes},
        ).scalar_one_or_none()
        if active is not None:
            return OpenRunResult(
                opened=False, run_id=run_id, active_run_id=active, stale_runs_closed=int(stale or 0)
            )
        connection.execute(
            text(INSERT_RUN_SQL),
            {
                "run_id": run_id,
                "pipeline_name": PIPELINE_NAME,
                "trigger": trigger,
                "triggered_by": triggered_by,
                "prefect_flow_run_id": prefect_flow_run_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )
    return OpenRunResult(opened=True, run_id=run_id, stale_runs_closed=int(stale or 0))


def heartbeat(
    engine: Engine,
    run_id: UUID,
    phase: str,
    *,
    events_extracted: int | None = None,
    duplicates_dropped: int | None = None,
    events_excluded: int | None = None,
    events_rejected: int | None = None,
    events_by_type: dict[str, int] | None = None,
    source_max_timestamp: Any = None,
) -> None:
    """Checkpoint de fase: `last_completed_phase` + `heartbeat_at` + conteos conocidos."""
    with engine.begin() as connection:
        connection.execute(
            text(HEARTBEAT_SQL),
            {
                "run_id": run_id,
                "phase": phase,
                "events_extracted": events_extracted,
                "duplicates_dropped": duplicates_dropped,
                "events_excluded": events_excluded,
                "events_rejected": events_rejected,
                "events_by_type": _json_or_none(events_by_type),
                "source_max_timestamp": source_max_timestamp,
            },
        )


def close_run(
    engine: Engine,
    run_id: UUID,
    *,
    status: str,
    warnings: list[str] | None = None,
    capture_coverage: dict[str, Any] | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    """Cierra la corrida en `completed` o `failed` con su duración y errores."""
    if status not in {"completed", "failed"}:
        raise ValueError("status debe ser 'completed' o 'failed'.")
    if error_message is not None:
        error_message = error_message[:ERROR_MESSAGE_MAX_LENGTH]
    with engine.begin() as connection:
        connection.execute(
            text(CLOSE_RUN_SQL),
            {
                "run_id": run_id,
                "status": status,
                "warnings": json.dumps(warnings or []),
                "capture_coverage": _json_or_none(capture_coverage),
                "error_type": error_type,
                "error_message": error_message,
            },
        )


def find_active_run(engine: Engine, stale_minutes: int) -> UUID | None:
    """`run_id` de la corrida viva (con heartbeat reciente), si la hay."""
    with engine.connect() as connection:
        return connection.execute(
            text(ACTIVE_RUN_SQL),
            {"pipeline_name": PIPELINE_NAME, "stale_minutes": stale_minutes},
        ).scalar_one_or_none()


def get_latest_run(engine: Engine) -> dict[str, Any] | None:
    """Última corrida del pipeline, o `None` si nunca corrió."""
    with engine.connect() as connection:
        row = connection.execute(
            text(LATEST_RUN_SQL), {"pipeline_name": PIPELINE_NAME}
        ).mappings().first()
    return None if row is None else dict(row)
