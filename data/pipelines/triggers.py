"""Disparo manual del pipeline desde la API (§11.3 y §13.1 del diseño).

`POST /reporting/pipeline-runs` llama a `trigger_manual_run`: comprueba que no
haya otra corrida viva (409 en la API) y lanza el flow de `pipeline.py` en un
hilo aparte, para responder 202 sin esperar a que termine. La lógica del
pipeline no se duplica: el hilo ejecuta el mismo flow que el cron y el CLI.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging
import threading
from uuid import UUID, uuid4

from sqlalchemy.engine import Engine

from data.pipelines import runs
from data.pipelines.config import load_config


logger = logging.getLogger(__name__)


class PipelineRunAlreadyActiveError(RuntimeError):
    def __init__(self, active_run_id: UUID):
        self.active_run_id = active_run_id
        super().__init__(f"Ya hay una corrida en marcha: {active_run_id}")


@dataclass(frozen=True)
class ManualRun:
    run_id: UUID
    status: str
    week_start: date | None


def run_flow(run_id: UUID, week_start: date | None, triggered_by: str | None) -> None:
    """Ejecuta el flow; los errores quedan en pipeline_runs y en el log de la API."""
    from data.pipelines.pipeline import weekly_warehouse_client_performance_flow

    try:
        weekly_warehouse_client_performance_flow(
            week_start=week_start,
            trigger="manual",
            run_id=run_id,
            triggered_by=triggered_by,
        )
    except Exception:
        logger.exception("La corrida manual %s terminó con error", run_id)


def trigger_manual_run(
    engine: Engine,
    *,
    week_start: date | None = None,
    triggered_by: str | None = None,
) -> ManualRun:
    """Valida, comprueba concurrencia y lanza la corrida en segundo plano."""
    if week_start is not None and week_start.weekday() != 0:
        raise ValueError("week_start debe ser un lunes (inicio de semana ISO).")
    active = runs.find_active_run(engine, load_config().stale_run_minutes)
    if active is not None:
        raise PipelineRunAlreadyActiveError(active)
    run_id = uuid4()
    threading.Thread(
        target=run_flow,
        args=(run_id, week_start, triggered_by),
        name=f"pipeline-run-{run_id}",
        daemon=True,
    ).start()
    return ManualRun(run_id=run_id, status="pending", week_start=week_start)
