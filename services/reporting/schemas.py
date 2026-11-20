"""Contratos de respuesta de `services/reporting/`.

`WeeklyWarehouseClientPerformance` reproduce exactamente el JSON de la sección 6
del BRIEFING de data pipelines: es lo que consumirá el dashboard de la Parte 3.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WeeklyWarehouseClientPerformanceEntry(BaseModel):
    warehouse: str
    client_id: str
    inbound_units_count: int
    outbound_orders_count: int
    stockout_events_count: int
    discrepancy_events_count: int
    discrepancy_rate: float


class WeeklyWarehouseClientPerformance(BaseModel):
    week_start: date
    entries: list[WeeklyWarehouseClientPerformanceEntry]


class PipelineRunStatus(BaseModel):
    run_id: UUID
    pipeline_name: str
    trigger: Literal["scheduled", "manual", "backfill"]
    triggered_by: str | None
    prefect_flow_run_id: UUID | None
    status: Literal["running", "completed", "failed"]
    last_completed_phase: str | None
    window_start: date
    window_end: date
    started_at: datetime
    heartbeat_at: datetime
    finished_at: datetime | None
    loaded_at: datetime | None
    duration_ms: int | None
    records_processed: int
    events_extracted: int
    duplicates_dropped: int
    events_excluded: int
    events_rejected: int
    events_by_type: dict[str, int]
    rows_inserted: int
    rows_updated: int
    rows_unchanged: int
    rows_deleted: int
    source_max_timestamp: datetime | None
    capture_coverage: dict[str, Any]
    warnings: list[str]
    error_type: str | None
    error_message: str | None


class PipelineRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_start: date | None = None


class PipelineRunAccepted(BaseModel):
    """202 de `POST /reporting/pipeline-runs`: la tarea está encolada, no terminada.

    `task_id` se consulta en `GET /tasks/{task_id}`; `run_id` es el id de la fila
    del primer intento en `reporting.pipeline_runs` (el mismo valor).
    """

    task_id: str
    run_id: UUID
    status: Literal["pending"]
    week_start: date | None
