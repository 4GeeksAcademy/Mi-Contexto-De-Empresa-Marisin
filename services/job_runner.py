"""Control de estado de los jobs en segundo plano (`public.job_runs`).

La tabla se crea con `services/sql/001_job_runs.sql`. Este módulo ofrece las
funciones para crear, actualizar y consultar ejecuciones, y `run_job()`, que
recorre la máquina de estados completa alrededor del trabajo de un job:

    pending → processing → completed
                        ↘ failed

- El lock distribuido es el propio estado `processing` (J3 del plan): el índice
  único parcial `job_runs_single_processing_idx` hace atómica la transición
  pending → processing; si otra instancia ya la tiene, la actualización falla
  con `IntegrityError` y esta instancia aborta. No hay otro mecanismo de lock.
- La idempotencia es por `(job_name, target_date)` (J4): si ya hay una fila
  `completed` para ese día, el trabajo no se repite.
- Ninguna fila queda en `processing` tras un fallo (J5): cualquier excepción,
  incluidas `SystemExit` (SIGTERM) y `KeyboardInterrupt`, pasa la fila a
  `failed` con el mensaje y se vuelve a lanzar; el `finally` reintenta el cierre
  si el primero falló, y las filas `processing` huérfanas de un proceso muerto
  sin poder reaccionar (SIGKILL, apagón) las cierra la siguiente ejecución.

Las horas se calculan en Python (UTC) y no con `now()` de SQL, para que el
mismo código funcione en Postgres (Supabase) y en el SQLite en memoria de los
tests. Este módulo no importa nada de FastAPI.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
import logging
import time
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Index,
    MetaData,
    Table,
    Text,
    Uuid,
    exists,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


PENDING = "pending"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"
STATUSES = (PENDING, PROCESSING, COMPLETED, FAILED)

ERROR_MESSAGE_MAX_LENGTH = 1000

# Metadata propia, fuera de `SQLModel.metadata`: la API nunca crea esta tabla
# con `create_all()`; en producción la crea el SQL versionado.
job_runs_metadata = MetaData()

job_runs = Table(
    "job_runs",
    job_runs_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("job_name", Text, nullable=False),
    Column("target_date", Date, nullable=False),
    Column("status", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("finished_at", DateTime(timezone=True), nullable=True),
    Column("error_message", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("job_runs_job_name_target_date_idx", "job_name", "target_date"),
    Index(
        "job_runs_single_processing_idx",
        "job_name",
        unique=True,
        postgresql_where=text("status = 'processing'"),
        sqlite_where=text("status = 'processing'"),
    ),
)


class JobOutcome(str, Enum):
    """Resultado de una invocación de `run_job()`."""

    COMPLETED = "completed"
    SKIPPED_LOCKED = "skipped_locked"
    SKIPPED_DUPLICATE = "skipped_duplicate"


@dataclass(frozen=True)
class JobResult:
    outcome: JobOutcome
    run_id: UUID | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _truncate(message: str) -> str:
    return message if len(message) <= ERROR_MESSAGE_MAX_LENGTH else message[: ERROR_MESSAGE_MAX_LENGTH - 1] + "…"


def describe_exception(exc: BaseException) -> str:
    """`Tipo: mensaje` de la excepción, recortado para `error_message`."""
    detail = str(exc).strip()
    return _truncate(f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__)


# ---------------------------------------------------------------------------
# Logs: cada línea lleva timestamp UTC, nombre del job y estado resultante
# ---------------------------------------------------------------------------


LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | job=%(job)s | status=%(status)s"
    " | target_date=%(target_date)s | run_id=%(run_id)s | %(message)s"
)
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class _JobContextFilter(logging.Filter):
    """Rellena los campos del formato si una línea no los trae."""

    def filter(self, record: logging.LogRecord) -> bool:
        for field in ("job", "status", "target_date", "run_id"):
            if not hasattr(record, field):
                setattr(record, field, "-")
        return True


def configure_job_logging(logger_name: str, level: int = logging.INFO) -> logging.Logger:
    """Logger del job hacia stdout (el cron lo redirige al fichero de log)."""
    import sys

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        handler.addFilter(_JobContextFilter())
        logger.addHandler(handler)
    return logger


def log_event(
    logger: logging.Logger,
    level: int,
    status: str,
    message: str,
    *args: Any,
    job_name: str,
    target_date: date | None = None,
    run_id: UUID | None = None,
    exc_info: bool = False,
) -> None:
    logger.log(
        level,
        message,
        *args,
        exc_info=exc_info,
        extra={
            "job": job_name,
            "status": status,
            "target_date": target_date.isoformat() if target_date else "-",
            "run_id": str(run_id) if run_id else "-",
        },
    )


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------


def has_processing_lock(engine: Engine, job_name: str) -> bool:
    """¿Hay ahora mismo una ejecución `processing` de este job (lock tomado)?"""
    query = select(
        exists().where(job_runs.c.job_name == job_name, job_runs.c.status == PROCESSING)
    )
    with engine.connect() as connection:
        return bool(connection.execute(query).scalar())


def has_completed_for_date(engine: Engine, job_name: str, target_date: date) -> bool:
    """¿Ya hay una ejecución `completed` de este job para este día?"""
    query = select(
        exists().where(
            job_runs.c.job_name == job_name,
            job_runs.c.target_date == target_date,
            job_runs.c.status == COMPLETED,
        )
    )
    with engine.connect() as connection:
        return bool(connection.execute(query).scalar())


def get_run(engine: Engine, run_id: UUID) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = connection.execute(select(job_runs).where(job_runs.c.id == run_id)).mappings().first()
    return None if row is None else dict(row)


def list_runs(engine: Engine, job_name: str, target_date: date | None = None) -> list[dict[str, Any]]:
    """Ejecuciones de un job (opcionalmente de un día), de la más antigua a la más reciente."""
    query = select(job_runs).where(job_runs.c.job_name == job_name)
    if target_date is not None:
        query = query.where(job_runs.c.target_date == target_date)
    query = query.order_by(job_runs.c.created_at, job_runs.c.id)
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(query).mappings()]


# ---------------------------------------------------------------------------
# Transiciones
# ---------------------------------------------------------------------------


def create_run(engine: Engine, job_name: str, target_date: date) -> UUID:
    """Crea el registro en `pending` antes de empezar."""
    run_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(job_runs).values(
                id=run_id,
                job_name=job_name,
                target_date=target_date,
                status=PENDING,
                created_at=utc_now(),
            )
        )
    return run_id


def mark_processing(engine: Engine, run_id: UUID) -> bool:
    """pending → processing: toma el lock. `False` si otra instancia ya lo tiene."""
    statement = (
        update(job_runs)
        .where(job_runs.c.id == run_id, job_runs.c.status == PENDING)
        .values(status=PROCESSING, started_at=utc_now())
    )
    try:
        with engine.begin() as connection:
            updated = connection.execute(statement).rowcount
    except IntegrityError:
        # job_runs_single_processing_idx: ya hay otra fila processing de este job.
        return False
    if updated != 1:
        raise RuntimeError(f"La ejecución {run_id} no está en pending: no se puede pasar a processing.")
    return True


def _finish(engine: Engine, run_id: UUID, status: str, error_message: str | None) -> None:
    statement = (
        update(job_runs)
        .where(job_runs.c.id == run_id, job_runs.c.status.in_((PENDING, PROCESSING)))
        .values(
            status=status,
            finished_at=utc_now(),
            error_message=None if error_message is None else _truncate(error_message),
        )
    )
    with engine.begin() as connection:
        connection.execute(statement)


def mark_completed(engine: Engine, run_id: UUID) -> None:
    """processing → completed: solo si todo terminó bien. Libera el lock."""
    _finish(engine, run_id, COMPLETED, None)


def mark_failed(engine: Engine, run_id: UUID, error_message: str) -> None:
    """pending | processing → failed con el mensaje del error. Libera el lock."""
    _finish(engine, run_id, FAILED, error_message)


def recover_stale_runs(engine: Engine, job_name: str, older_than: timedelta) -> int:
    """Cierra en `failed` las filas `processing` más viejas que `older_than`.

    Solo pasa si el proceso que tenía el lock murió sin poder reaccionar
    (SIGKILL, apagón del contenedor). Sin esto, esa fila bloquearía el job para
    siempre. `older_than` debe superar la duración máxima de una ejecución.
    """
    now = utc_now()
    statement = (
        update(job_runs)
        .where(
            job_runs.c.job_name == job_name,
            job_runs.c.status == PROCESSING,
            job_runs.c.started_at < now - older_than,
        )
        .values(
            status=FAILED,
            finished_at=now,
            error_message=(
                "StaleRun: la ejecución siguió en processing más de "
                f"{int(older_than.total_seconds() // 60)} min; el proceso terminó sin cerrarla."
            ),
        )
    )
    with engine.begin() as connection:
        return int(connection.execute(statement).rowcount or 0)


# ---------------------------------------------------------------------------
# Máquina de estados completa
# ---------------------------------------------------------------------------


def run_job(
    engine: Engine,
    *,
    job_name: str,
    target_date: date,
    work: Callable[[UUID], None],
    logger: logging.Logger,
    stale_after: timedelta,
) -> JobResult:
    """Ejecuta `work` dentro de la máquina de estados de `job_runs`.

    1. Cierra filas `processing` huérfanas (más viejas que `stale_after`).
    2. Si hay lock (`processing`) → aborta en silencio (`SKIPPED_LOCKED`).
    3. Si ya hay `completed` para el día → omite por duplicado (`SKIPPED_DUPLICATE`).
    4. Crea la fila `pending` y la pasa a `processing` (toma el lock de forma atómica).
    5. Ejecuta `work(run_id)` → `completed`; cualquier excepción → `failed` y se relanza.

    Las omisiones de los pasos 2 y 3 no crean fila: se registran en el log. Una
    fila creada nunca queda en `pending` ni `processing`.
    """
    ctx = {"job_name": job_name, "target_date": target_date}

    stale = recover_stale_runs(engine, job_name, stale_after)
    if stale:
        log_event(
            logger, logging.WARNING, FAILED,
            "%d ejecución(es) processing huérfana(s) cerrada(s) en failed (StaleRun).", stale, **ctx,
        )

    if has_processing_lock(engine, job_name):
        log_event(
            logger, logging.INFO, "skipped",
            "Otra instancia está en processing (lock tomado): esta se cancela sin hacer nada.", **ctx,
        )
        return JobResult(JobOutcome.SKIPPED_LOCKED, None)

    if has_completed_for_date(engine, job_name, target_date):
        log_event(
            logger, logging.INFO, "skipped",
            "Ya hay una ejecución completed para este día: omisión por duplicado.", **ctx,
        )
        return JobResult(JobOutcome.SKIPPED_DUPLICATE, None)

    run_id = create_run(engine, job_name, target_date)
    ctx["run_id"] = run_id
    log_event(logger, logging.INFO, PENDING, "Ejecución registrada.", **ctx)

    closed = False
    try:
        if not mark_processing(engine, run_id):
            # Carrera perdida: otra instancia tomó el lock entre la comprobación y la transición.
            mark_failed(engine, run_id, "Aborted: otra instancia tomó el lock (processing) mientras arrancaba esta; no se hizo ningún trabajo.")
            closed = True
            log_event(
                logger, logging.INFO, "skipped",
                "Lock perdido frente a otra instancia: esta se cancela (fila cerrada en failed, sin trabajo).", **ctx,
            )
            return JobResult(JobOutcome.SKIPPED_LOCKED, run_id)

        if has_completed_for_date(engine, job_name, target_date):
            # Otra instancia completó el día justo antes de que esta tomara el lock.
            mark_failed(engine, run_id, "Aborted: el día ya estaba completed al tomar el lock; no se hizo ningún trabajo.")
            closed = True
            log_event(logger, logging.INFO, "skipped", "Omisión por duplicado tras tomar el lock.", **ctx)
            return JobResult(JobOutcome.SKIPPED_DUPLICATE, run_id)

        log_event(logger, logging.INFO, PROCESSING, "Inicio del trabajo (lock tomado).", **ctx)
        work(run_id)
        mark_completed(engine, run_id)
        closed = True
        log_event(logger, logging.INFO, COMPLETED, "Fin del trabajo: ejecución completada.", **ctx)
        return JobResult(JobOutcome.COMPLETED, run_id)
    except BaseException as exc:  # también SystemExit (SIGTERM) y KeyboardInterrupt
        message = describe_exception(exc)
        try:
            mark_failed(engine, run_id, message)
            closed = True
        finally:
            log_event(
                logger, logging.ERROR, FAILED, "La ejecución falló: %s", message, exc_info=True, **ctx,
            )
        raise
    finally:
        if not closed:
            # El primer cierre en failed no llegó a la base de datos: un reintento más.
            try:
                mark_failed(engine, run_id, "Unfinished: no se pudo registrar el cierre de la ejecución.")
            except Exception:
                log_event(
                    logger, logging.ERROR, PROCESSING,
                    "No se pudo cerrar la fila; la siguiente ejecución la marcará como StaleRun.",
                    exc_info=True, **ctx,
                )
