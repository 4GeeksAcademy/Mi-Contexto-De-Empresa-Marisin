"""`GET /tasks/{task_id}`: estado de una tarea asíncrona de Celery (Ticket #DEV-55).

Lee el result backend (Redis) con `AsyncResult`; no toca la base de datos ni
espera a que la tarea termine. `status` traduce los estados reales de Celery a
los cuatro del ticket y `celery_state` los devuelve tal cual:

| `celery_state`        | `status`  | Significado                                        |
|-----------------------|-----------|----------------------------------------------------|
| `PENDING`, `RECEIVED` | `pending` | En la cola (o id desconocido: Celery no los distingue). |
| `RETRY`               | `pending` | Falló un intento y espera en la cola su backoff.   |
| `STARTED`             | `started` | Un worker la está ejecutando.                      |
| `SUCCESS`             | `success` | Terminó; `result` trae lo que devolvió.            |
| `FAILURE`, `REVOKED`  | `failure` | Agotó sus reintentos (DLQ) o se canceló.           |

`error` solo lleva el tipo y el mensaje de la excepción, nunca la traza.
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..security import get_current_user

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services import celery_app as task_queue
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.celery_app"}:
        raise
    # Contenedor de Docker: /app es `services/`.
    import celery_app as task_queue


router = APIRouter(prefix="/tasks", tags=["tasks"])

TaskStatusValue = Literal["pending", "started", "success", "failure"]

CELERY_TO_STATUS: dict[str, TaskStatusValue] = {
    "PENDING": "pending",
    "RECEIVED": "pending",
    "RETRY": "pending",
    "STARTED": "started",
    "SUCCESS": "success",
    "FAILURE": "failure",
    "REVOKED": "failure",
}

RESULT_BACKEND_UNAVAILABLE = "Task result backend unavailable"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatusValue
    celery_state: str
    result: Any | None = None
    error: str | None = None


def _async_result(task_id: str):
    return task_queue.app.AsyncResult(task_id)


def _error_text(value: Any) -> str | None:
    if isinstance(value, BaseException):
        return f"{type(value).__name__}: {value}"
    return None if value is None else str(value)


def build_task_status(task_id: str, celery_state: str, payload: Any) -> TaskStatusResponse:
    task_status = CELERY_TO_STATUS.get(celery_state, "pending")
    if celery_state == "SUCCESS":
        return TaskStatusResponse(task_id=task_id, status=task_status, celery_state=celery_state, result=payload)
    if celery_state in {"FAILURE", "RETRY", "REVOKED"}:
        return TaskStatusResponse(
            task_id=task_id, status=task_status, celery_state=celery_state, error=_error_text(payload)
        )
    # PENDING / RECEIVED / STARTED: el backend puede guardar metadatos del worker
    # (pid, hostname) que no son el resultado.
    return TaskStatusResponse(task_id=task_id, status=task_status, celery_state=celery_state)


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: UUID,
    _: Annotated[dict, Depends(get_current_user)],
) -> TaskStatusResponse:
    """Estado actual de la tarea y su resultado cuando está disponible."""
    task_key = str(task_id)
    try:
        async_result = _async_result(task_key)
        celery_state = str(async_result.state)
        payload = async_result.result if celery_state in {"SUCCESS", "FAILURE", "RETRY", "REVOKED"} else None
    except Exception as exc:  # redis.ConnectionError, OSError…
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=RESULT_BACKEND_UNAVAILABLE
        ) from exc
    return build_task_status(task_key, celery_state, payload)
