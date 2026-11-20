"""Cola de tareas asíncronas de TrackFlow (Ticket #DEV-55): Celery + Redis.

Patrón productor / consumidor:

    Cliente → API (productor) → Redis (broker) → worker Celery (consumidor) → resultado

- **Productor:** la API solo llama a `enqueue_pipeline_run()`, que publica un mensaje
  ligero (identificadores, nunca datos) con `send_task` por **nombre**: la API no
  importa el código de las tareas ni Prefect.
- **Broker y result backend:** el mismo Redis, cuya URL se lee de `REDIS_URL`.
- **Consumidor:** un proceso aparte, `celery -A services.celery_app worker -l info`.
  Nunca corre dentro de uvicorn.

Reglas del patrón aplicadas en la configuración:

1. Mensajes ligeros: `run_pipeline` recibe `week_start` y `triggered_by`; el worker
   lee los eventos de la base de datos él mismo.
2. ACK solo tras terminar: `task_acks_late` + `task_reject_on_worker_lost`. Si el
   worker muere a mitad de una tarea, el mensaje vuelve a la cola.
3. Toda tarea tiene timeout: `task_soft_time_limit` / `task_time_limit` globales,
   y límites propios en cada tarea.

Observabilidad: las señales de Celery registran en el log de cada ejecución el
`task_id`, el intento, el estado resultante y la duración; los fallos, además, el
error completo con su traza.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any
from uuid import UUID

from celery import Celery, signals
from kombu import Queue


DEFAULT_REDIS_URL = "redis://localhost:6379/0"

# Nombres estables de las tareas: no dependen de la ruta del módulo, que cambia
# entre el Codespace (`services.tasks`) y el contenedor (`tasks`, porque /app es services/).
RUN_PIPELINE_TASK = "trackflow.reporting.run_pipeline"
RECORD_DEAD_LETTER_TASK = "trackflow.dead_letter.record"

DEFAULT_QUEUE = "celery"
DEAD_LETTER_QUEUE = "dead_letter"

# Backoff exponencial entre reintentos: base · 2^reintentos_previos → 5 s, 10 s, 20 s.
MAX_RETRIES = 3
RETRY_BASE_SECONDS = int(os.getenv("TRACKFLOW_TASK_RETRY_BASE_SECONDS", "5"))

# Límites globales; cada tarea fija los suyos.
SOFT_TIME_LIMIT_SECONDS = 600
TIME_LIMIT_SECONDS = 660


def redis_url() -> str:
    """URL del broker y del result backend (la misma para la API y los workers)."""
    return os.getenv("REDIS_URL", "").strip() or DEFAULT_REDIS_URL


def _tasks_module() -> str:
    package = __name__.rpartition(".")[0]
    return f"{package}.tasks" if package else "tasks"


app = Celery("trackflow", broker=redis_url(), backend=redis_url(), include=[_tasks_module()])
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Estados reales: PENDING → STARTED → (RETRY → STARTED)* → SUCCESS | FAILURE.
    task_track_started=True,
    result_extended=True,
    result_expires=24 * 60 * 60,
    # ACK solo cuando la tarea termina; si el worker muere, el mensaje se reentrega.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # Con Redis, un mensaje sin ACK vuelve a la cola pasado este tiempo: debe superar
    # el time limit más largo y el countdown máximo de los reintentos.
    broker_transport_options={"visibility_timeout": 3600},
    task_soft_time_limit=SOFT_TIME_LIMIT_SECONDS,
    task_time_limit=TIME_LIMIT_SECONDS,
    # Si Redis no responde, la API devuelve 503 en lugar de quedarse colgada.
    broker_connection_timeout=2,
    broker_connection_retry_on_startup=True,
    # Eventos para Flower: tareas encoladas (sent), en proceso y terminadas.
    worker_send_task_events=True,
    task_send_sent_event=True,
    # El worker consume las dos colas: la normal y la Dead Letter Queue.
    task_default_queue=DEFAULT_QUEUE,
    task_queues=(Queue(DEFAULT_QUEUE), Queue(DEAD_LETTER_QUEUE)),
    task_routes={RECORD_DEAD_LETTER_TASK: {"queue": DEAD_LETTER_QUEUE}},
)

# Alias para quien importe la instancia con un nombre explícito.
celery_app = app


def retry_countdown(retries_done: int) -> int:
    """Segundos de espera antes del siguiente intento (backoff exponencial)."""
    return RETRY_BASE_SECONDS * (2**retries_done)


# ---------------------------------------------------------------------------
# Productor (lo usa la API)
# ---------------------------------------------------------------------------


class BrokerUnavailableError(RuntimeError):
    """No se pudo publicar el mensaje en Redis."""


def enqueue_pipeline_run(task_id: UUID, week_start: str | None, triggered_by: str | None) -> str:
    """Encola una corrida del pipeline y devuelve el `task_id` sin esperar a que termine.

    El mensaje solo lleva referencias: el lunes de la semana (o `None`) y quién la pidió.
    `retry=False`: un único intento de publicación, limitado por `broker_connection_timeout`.
    """
    try:
        result = app.send_task(
            RUN_PIPELINE_TASK,
            kwargs={"week_start": week_start, "triggered_by": triggered_by},
            task_id=str(task_id),
            queue=DEFAULT_QUEUE,
            retry=False,
        )
    except Exception as exc:  # kombu.OperationalError, redis.ConnectionError, OSError…
        raise BrokerUnavailableError(f"{type(exc).__name__}: {exc}") from exc
    return result.id


# ---------------------------------------------------------------------------
# Observabilidad: una línea de log por ejecución
# ---------------------------------------------------------------------------

task_logger = logging.getLogger("trackflow.tasks")
_started_at: dict[str, float] = {}


def _attempt(task: Any) -> int:
    request = getattr(task, "request", None)
    return int(getattr(request, "retries", 0) or 0) + 1


@signals.task_prerun.connect
def _log_task_start(task_id: str | None = None, task: Any = None, **_: Any) -> None:
    if task_id is None:
        return
    _started_at[task_id] = time.perf_counter()
    task_logger.info(
        "task=%s task_id=%s attempt=%s state=STARTED",
        getattr(task, "name", "?"),
        task_id,
        _attempt(task),
    )


@signals.task_postrun.connect
def _log_task_end(task_id: str | None = None, task: Any = None, state: str | None = None, **_: Any) -> None:
    if task_id is None:
        return
    started = _started_at.pop(task_id, None)
    duration_ms = (time.perf_counter() - started) * 1000 if started is not None else -1.0
    level = logging.INFO if state == "SUCCESS" else logging.WARNING
    task_logger.log(
        level,
        "task=%s task_id=%s attempt=%s state=%s duration_ms=%.1f",
        getattr(task, "name", "?"),
        task_id,
        _attempt(task),
        state,
        duration_ms,
    )


@signals.task_retry.connect
def _log_task_retry(request: Any = None, reason: Any = None, einfo: Any = None, **_: Any) -> None:
    retries_done = int(getattr(request, "retries", 0) or 0)
    task_logger.warning(
        "task=%s task_id=%s attempt=%s state=RETRY next_attempt_in=%ss error=%s\n%s",
        getattr(request, "task", "?"),
        getattr(request, "id", "?"),
        retries_done + 1,
        retry_countdown(retries_done),
        reason,
        getattr(einfo, "traceback", "") or "",
    )


@signals.task_failure.connect
def _log_task_failure(
    sender: Any = None, task_id: str | None = None, exception: BaseException | None = None, einfo: Any = None, **_: Any
) -> None:
    task_logger.error(
        "task=%s task_id=%s attempt=%s state=FAILURE error=%s: %s\n%s",
        getattr(sender, "name", "?"),
        task_id,
        _attempt(sender),
        type(exception).__name__ if exception is not None else "?",
        exception,
        getattr(einfo, "traceback", "") or "",
    )
