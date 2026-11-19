"""Corrida manual del pipeline desde la cola de tareas (§11.3 y §13.1 del diseño).

Desde el Ticket #DEV-55, `POST /reporting/pipeline-runs` ya no lanza el flow en un
hilo dentro de FastAPI: encola la tarea `trackflow.reporting.run_pipeline`
(`services/tasks.py`) y responde 202 con su `task_id`. Un worker de Celery, en un
proceso aparte, llama a `run_manual_flow()`.

La lógica del pipeline no se duplica: se ejecuta el mismo flow que el cron y el
CLI. La concurrencia la sigue resolviendo `pipeline_runs` (advisory lock + estado
`running`): si ya hay una corrida viva, el flow termina en `Cancelled`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class ManualRunOutcome:
    status: str  # "completed" | "cancelled" | "failed"
    summary: dict[str, Any] | None = None
    message: str | None = None
    error: BaseException | None = None


def run_manual_flow(run_id: UUID, week_start: date | None, triggered_by: str | None) -> ManualRunOutcome:
    """Ejecuta el flow con `return_state=True` y traduce su state final.

    - `Completed` → `completed` con el resumen de la corrida.
    - `Cancelled` (otra corrida viva) → `cancelled`: no es un fallo y no se reintenta.
    - Cualquier otro state → `failed` con la excepción original.
    """
    from data.pipelines.pipeline import weekly_warehouse_client_performance_flow

    state = weekly_warehouse_client_performance_flow(
        week_start=week_start,
        trigger="manual",
        run_id=run_id,
        triggered_by=triggered_by,
        return_state=True,
    )
    if state.is_completed():
        return ManualRunOutcome(status="completed", summary=state.result())
    if state.is_cancelled():
        return ManualRunOutcome(status="cancelled", message=state.message)
    cause = state.result(raise_on_failure=False)
    error = cause if isinstance(cause, BaseException) else RuntimeError(state.message or str(cause))
    return ManualRunOutcome(status="failed", message=state.message, error=error)
