"""Script nocturno de telemetría (Ticket #DEV-53).

Cada noche, sin intervención manual (lo dispara el crontab del sistema, J7):

1. Resuelve el día objetivo: `TARGET_DATE=AAAA-MM-DD` o, por defecto, ayer en UTC.
2. Exporta las filas de `telemetry_events` de ese día a
   `data/raw/telemetry_AAAA-MM-DD.csv`, solo si el fichero no existe. El CSV es
   un snapshot de backup y auditoría: el pipeline lee de la base de datos, no
   de este fichero.
3. Lanza el Pipeline de Desempeño de Negocio (Hito 6) como subproceso.
4. Deja constancia en `public.job_runs` (pending → processing → completed |
   failed) a través de `services/job_runner.py`.

Es un proceso independiente de la API: no importa FastAPI ni nada de
`services/api/` y usa su propio engine (el del pipeline, `data/pipelines/config.py`).

Uso (desde la raíz del repo, con el entorno virtual activado):

    python scripts/nightly_export.py                         # ayer (UTC)
    TARGET_DATE=2026-11-18 python scripts/nightly_export.py  # un día concreto

Variables de entorno opcionales:

- `TARGET_DATE`: día objetivo `AAAA-MM-DD` (pruebas y recuperación).
- `NIGHTLY_EXPORT_PIPELINE_TIMEOUT_SECONDS`: tiempo máximo del subproceso del
  pipeline (por defecto 3600).
- `NIGHTLY_EXPORT_STALE_MINUTES`: minutos tras los que una fila `processing`
  se considera huérfana (por defecto 120; debe superar el timeout del pipeline).

Códigos de salida: 0 completado u omitido (lock tomado o día ya completado),
1 la ejecución falló, 2 configuración inválida (p. ej. `TARGET_DATE` mal escrito).
"""

from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, Mapping
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
# Ejecutado como script, Python solo añade `scripts/` al path: se añade la raíz
# del repo para importar `services.*` y `data.*`.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import DateTime, bindparam, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from services import job_runner  # noqa: E402
from services.job_runner import log_event  # noqa: E402


JOB_NAME = "nightly_export"
LOGGER_NAME = "trackflow.jobs.nightly_export"
RAW_DIR = REPO_ROOT / "data" / "raw"
CSV_COLUMNS = ("id", "timestamp", "service", "event_type", "level", "value", "message", "tags")
DEFAULT_PIPELINE_TIMEOUT_SECONDS = 3600
DEFAULT_STALE_MINUTES = 120

# Sin prefijo de esquema: en Supabase `telemetry_events` se resuelve en `public`
# (search_path por defecto) y así la misma consulta funciona en el SQLite de los tests.
EXPORT_SQL = (
    text(
        """
        select id, "timestamp", service, event_type, level, value, message, tags
        from telemetry_events
        where "timestamp" >= :day_start
          and "timestamp" <  :day_end
        order by "timestamp", id
        """
    )
    .bindparams(
        bindparam("day_start", type_=DateTime(timezone=True)),
        bindparam("day_end", type_=DateTime(timezone=True)),
    )
    .columns(timestamp=DateTime(timezone=True))
)


class ConfigurationError(ValueError):
    """Variable de entorno con un valor inválido."""


class PipelineSubprocessError(RuntimeError):
    """El subproceso del pipeline terminó con código distinto de 0."""


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------


def resolve_target_date(env: Mapping[str, str] | None = None, today: date | None = None) -> tuple[date, bool]:
    """Día objetivo y si viene de `TARGET_DATE` (`True`) o es ayer en UTC (`False`)."""
    env = os.environ if env is None else env
    raw = env.get("TARGET_DATE", "").strip()
    if raw:
        try:
            return date.fromisoformat(raw), True
        except ValueError as exc:
            raise ConfigurationError(f"TARGET_DATE debe tener el formato AAAA-MM-DD; recibido {raw!r}.") from exc
    today = today or datetime.now(timezone.utc).date()
    return today - timedelta(days=1), False


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} debe ser un entero positivo; recibido {raw!r}.") from exc
    if value <= 0:
        raise ConfigurationError(f"{name} debe ser un entero positivo; recibido {raw!r}.")
    return value


# ---------------------------------------------------------------------------
# Paso 1: snapshot CSV de telemetry_events
# ---------------------------------------------------------------------------


def csv_path_for(target_date: date, raw_dir: Path | None = None) -> Path:
    return (raw_dir or RAW_DIR) / f"telemetry_{target_date.isoformat()}.csv"


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _csv_value(column: str, value: Any) -> Any:
    if value is None:
        return ""
    if column == "timestamp" and isinstance(value, datetime):
        if value.tzinfo is None:  # SQLite no guarda la zona: los timestamps son UTC
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if column == "tags" and not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    return value


def export_telemetry_csv(engine: Engine, target_date: date, raw_dir: Path | None = None) -> int | None:
    """Escribe el CSV del día si no existe. Devuelve las filas escritas, o `None` si ya existía.

    Se escribe primero en `<nombre>.csv.tmp` y se renombra al final (`os.replace`
    es atómico): si el proceso muere a medias nunca queda un CSV incompleto con
    el nombre definitivo, que la siguiente ejecución daría por bueno.
    """
    path = csv_path_for(target_date, raw_dir)
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    day_start, day_end = _day_bounds(target_date)
    tmp_path = path.with_name(path.name + ".tmp")
    rows = 0
    try:
        with engine.connect() as connection, tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(CSV_COLUMNS)
            result = connection.execute(EXPORT_SQL, {"day_start": day_start, "day_end": day_end})
            for row in result.mappings():
                writer.writerow([_csv_value(column, row[column]) for column in CSV_COLUMNS])
                rows += 1
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return rows


# ---------------------------------------------------------------------------
# Paso 2: subproceso del pipeline
# ---------------------------------------------------------------------------


def week_start_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def build_pipeline_command(target_date: date, overridden: bool) -> list[str]:
    """Entry point CLI del Hito 6 (`data/pipelines/pipeline.py`), J6 del plan.

    - Ejecución nocturna normal: sin `--week-start`, el pipeline recalcula las 4
      últimas semanas cerradas (incluye la que contiene a `target_date` en cuanto
      se cierra y absorbe eventos tardíos); la semana en curso nunca entra sola.
    - Con `TARGET_DATE`: recalcula la semana que contiene ese día (`backfill`).
    """
    command = [sys.executable, "-m", "data.pipelines.pipeline"]
    if overridden:
        return [*command, "--week-start", week_start_of(target_date).isoformat(), "--trigger", "backfill"]
    return [*command, "--trigger", "scheduled"]


def _tail(output: str, lines: int = 3) -> str:
    useful = [line.strip() for line in output.splitlines() if line.strip()]
    return " | ".join(useful[-lines:])


def _pipeline_summary(stdout: str) -> str:
    """Resumen del JSON que imprime el CLI del pipeline al terminar, si se puede leer."""
    try:
        summary = json.loads(stdout[stdout.index("{") :])
    except (ValueError, TypeError):
        return "sin resumen JSON"
    weeks = ",".join(summary.get("weeks", []))
    return (
        f"pipeline_run_id={summary.get('run_id')} status={summary.get('status')} weeks={weeks} "
        f"inserted={summary.get('rows_inserted')} updated={summary.get('rows_updated')}"
    )


def run_pipeline(command: list[str], timeout_seconds: int) -> str:
    """Lanza el pipeline y espera. Devuelve su resumen; lanza excepción si falla.

    `subprocess.run` mata al hijo si vence el timeout (`TimeoutExpired`) o si
    este proceso recibe SIGTERM mientras espera.
    """
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        detail = _tail(completed.stderr) or _tail(completed.stdout) or "sin salida"
        raise PipelineSubprocessError(f"el pipeline terminó con código {completed.returncode}: {detail}")
    return _pipeline_summary(completed.stdout)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _raise_system_exit_on_sigterm(signum: int, _frame: Any) -> None:
    # SIGTERM (kill, docker stop, cron parado) se convierte en SystemExit para que
    # run_job() lo capture, pase la fila a failed y libere el lock.
    raise SystemExit(128 + signum)


def main(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    logger = job_runner.configure_job_logging(LOGGER_NAME)
    signal.signal(signal.SIGTERM, _raise_system_exit_on_sigterm)

    try:
        target_date, overridden = resolve_target_date(env)
        timeout_seconds = _positive_int(env, "NIGHTLY_EXPORT_PIPELINE_TIMEOUT_SECONDS", DEFAULT_PIPELINE_TIMEOUT_SECONDS)
        stale_minutes = _positive_int(env, "NIGHTLY_EXPORT_STALE_MINUTES", DEFAULT_STALE_MINUTES)
    except ConfigurationError as exc:
        log_event(logger, logging.ERROR, "failed", "Configuración inválida: %s", exc, job_name=JOB_NAME)
        return 2

    log_event(
        logger, logging.INFO, "starting",
        "Arranque (pid=%d, fecha %s).", os.getpid(), "de TARGET_DATE" if overridden else "por defecto: ayer UTC",
        job_name=JOB_NAME, target_date=target_date,
    )
    if stale_minutes * 60 <= timeout_seconds:
        log_event(
            logger, logging.WARNING, "starting",
            "NIGHTLY_EXPORT_STALE_MINUTES (%d min) no supera el timeout del pipeline (%d s): "
            "una ejecución larga podría cerrarse como StaleRun.", stale_minutes, timeout_seconds,
            job_name=JOB_NAME, target_date=target_date,
        )

    def work(run_id: UUID) -> None:
        ctx = {"job_name": JOB_NAME, "target_date": target_date, "run_id": run_id}
        csv_path = csv_path_for(target_date)
        rows = export_telemetry_csv(engine, target_date)
        if rows is None:
            log_event(logger, logging.INFO, "processing", "CSV ya existente, no se reescribe: %s", _display(csv_path), **ctx)
        else:
            log_event(logger, logging.INFO, "processing", "CSV exportado: %s (%d filas).", _display(csv_path), rows, **ctx)

        command = build_pipeline_command(target_date, overridden)
        log_event(logger, logging.INFO, "processing", "Lanzando el pipeline: %s", " ".join(command[1:]), **ctx)
        summary = run_pipeline(command, timeout_seconds)
        log_event(logger, logging.INFO, "processing", "Pipeline terminado: %s", summary, **ctx)

    try:
        from data.pipelines.config import get_engine

        engine = get_engine()
        result = job_runner.run_job(
            engine,
            job_name=JOB_NAME,
            target_date=target_date,
            work=work,
            logger=logger,
            stale_after=timedelta(minutes=stale_minutes),
        )
    except SystemExit as exc:  # SIGTERM: run_job ya cerró la fila en failed y lo registró
        return exc.code if isinstance(exc.code, int) else 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # Si el fallo ocurrió antes de crear la fila (p. ej. sin conexión), solo queda el log.
        log_event(
            logger, logging.ERROR, "failed", "Ejecución terminada con error: %s",
            job_runner.describe_exception(exc), job_name=JOB_NAME, target_date=target_date,
        )
        return 1

    # COMPLETED, o SKIPPED_LOCKED / SKIPPED_DUPLICATE: omitida en silencio, no es un error.
    log_event(
        logger, logging.INFO, "finished", "Salida con código 0 (resultado: %s).", result.outcome.value,
        job_name=JOB_NAME, target_date=target_date, run_id=result.run_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
