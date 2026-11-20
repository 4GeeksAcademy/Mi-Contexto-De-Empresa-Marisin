"""Tareas de Celery de TrackFlow (Ticket #DEV-55). Solo las ejecuta el worker.

- `trackflow.reporting.run_pipeline`: la operación más pesada de la API, una corrida
  completa del Pipeline de Desempeño de Negocio (extracción de `telemetry_events`,
  transformación con Pandas, carga en `reporting` y snapshot). Reintentos: 3, con
  backoff exponencial (5 s, 10 s, 20 s). Si el cuarto intento también falla, la
  tarea termina en `FAILURE` y se publica un mensaje en la cola `dead_letter`.
- `trackflow.dead_letter.record`: consume la cola `dead_letter` y persiste el fallo
  en `public.task_dead_letters` (`task_id`, intento, error y timestamp).

Para la demostración de la DLQ, arrancar el worker con
`TRACKFLOW_TASKS_FORCE_FAILURE=1`: `run_pipeline` falla antes de tocar la base de
datos, en todos los intentos, sin cambiar el contrato de la API.
"""

from __future__ import annotations

from datetime import date
import logging
import os
from typing import Any
from uuid import UUID, uuid5

from celery.exceptions import Retry
from sqlalchemy.exc import SQLAlchemyError

try:
    # Worker arrancado desde la raíz del repo: `celery -A services.celery_app worker`.
    from services import dead_letter
    from services.celery_app import (
        DEAD_LETTER_QUEUE,
        MAX_RETRIES,
        RECORD_DEAD_LETTER_TASK,
        RUN_PIPELINE_TASK,
        app,
        retry_countdown,
    )
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.celery_app", "services.dead_letter"}:
        raise
    # Contenedor de Docker: /app es `services/`.
    import dead_letter  # type: ignore[no-redef]
    from celery_app import (  # type: ignore[no-redef]
        DEAD_LETTER_QUEUE,
        MAX_RETRIES,
        RECORD_DEAD_LETTER_TASK,
        RUN_PIPELINE_TASK,
        app,
        retry_countdown,
    )

from data.pipelines import triggers


logger = logging.getLogger("trackflow.tasks")

FORCE_FAILURE_ENV = "TRACKFLOW_TASKS_FORCE_FAILURE"


class SimulatedTaskFailure(RuntimeError):
    """Fallo provocado a propósito para demostrar reintentos y DLQ."""


def _force_failure_enabled() -> bool:
    return os.getenv(FORCE_FAILURE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _engine():
    """Engine del pipeline (`DATABASE_URL`); el worker no importa `services/api/`."""
    from data.pipelines.config import get_engine

    return get_engine()


def pipeline_run_id(task_id: str, attempt: int) -> UUID:
    """`run_id` de `reporting.pipeline_runs` para cada intento.

    El primero reutiliza el `task_id` (la API lo devuelve también como `run_id`);
    cada reintento abre su propia fila con un id derivado y determinista.
    """
    base = UUID(task_id)
    return base if attempt == 1 else uuid5(base, f"attempt-{attempt}")


def send_to_dead_letter(payload: dict[str, Any]) -> None:
    """Publica el fallo definitivo en la cola `dead_letter`."""
    record_dead_letter.apply_async(kwargs={"payload": payload}, queue=DEAD_LETTER_QUEUE)


@app.task(
    bind=True,
    name=RUN_PIPELINE_TASK,
    max_retries=MAX_RETRIES,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=600,
    time_limit=660,
)
def run_pipeline(self, week_start: str | None = None, triggered_by: str | None = None) -> dict[str, Any]:
    """Corrida manual del pipeline. El mensaje solo trae referencias, nunca datos."""
    attempt = self.request.retries + 1
    task_kwargs = {"week_start": week_start, "triggered_by": triggered_by}
    run_id = pipeline_run_id(self.request.id, attempt)
    try:
        if _force_failure_enabled():
            raise SimulatedTaskFailure(
                f"Fallo simulado ({FORCE_FAILURE_ENV}=1) en el intento {attempt} de la tarea {self.request.id}"
            )
        outcome = triggers.run_manual_flow(
            run_id, date.fromisoformat(week_start) if week_start else None, triggered_by
        )
        if outcome.status == "failed":
            error = outcome.error or RuntimeError(outcome.message or "pipeline failed")
            raise RuntimeError(f"La corrida {run_id} del pipeline falló: {type(error).__name__}: {error}") from error
    except Retry:
        raise
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.error(
                "task=%s task_id=%s attempt=%s reintentos agotados (%s): se envía a la DLQ",
                self.name,
                self.request.id,
                attempt,
                self.max_retries,
            )
            send_to_dead_letter(
                dead_letter.build_payload(
                    task_id=self.request.id,
                    task_name=self.name,
                    attempt=attempt,
                    max_retries=self.max_retries,
                    exc=exc,
                    task_kwargs=task_kwargs,
                )
            )
            raise
        raise self.retry(exc=exc, countdown=retry_countdown(self.request.retries))

    result: dict[str, Any] = {
        "pipeline_status": outcome.status,
        "run_id": str(run_id),
        "attempt": attempt,
        "week_start": week_start,
    }
    if outcome.status == "cancelled":
        result["message"] = outcome.message
    else:
        result["summary"] = outcome.summary
    return result


@app.task(
    bind=True,
    name=RECORD_DEAD_LETTER_TASK,
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(SQLAlchemyError,),
    max_retries=5,
    retry_backoff=5,
    retry_backoff_max=300,
    retry_jitter=False,
    soft_time_limit=30,
    time_limit=60,
)
def record_dead_letter(self, payload: dict[str, Any]) -> dict[str, Any]:
    """Consumidor de la DLQ: deja el fallo en `public.task_dead_letters`."""
    letter = dead_letter.from_payload(payload)
    inserted = dead_letter.record(_engine(), letter)
    logger.error(
        "DLQ task=%s task_id=%s attempt=%s error=%s: %s recorded=%s",
        letter.task_name,
        letter.task_id,
        letter.attempt,
        letter.error_type,
        letter.error_message,
        "inserted" if inserted else "already_present",
    )
    return {"task_id": letter.task_id, "attempt": letter.attempt, "recorded": inserted}
