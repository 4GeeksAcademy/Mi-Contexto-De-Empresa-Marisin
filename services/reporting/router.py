"""Endpoints del Pipeline de Desempeño de Negocio (BRIEFING de data pipelines §6).

- `GET  /reporting/weekly-warehouse-client-performance`: filas de KPIs (feed del dashboard).
- `GET  /reporting/pipeline-runs/latest`: estado y metadata de la última corrida.
- `POST /reporting/pipeline-runs`: dispara una corrida manual.

Sin lógica de ETL: validan la petición, llaman a `data/pipelines/` y traducen
errores a HTTP. Misma autenticación que el resto de la API (`get_current_user`).
"""

from datetime import date
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.api import database
    from services.api.security import get_current_user
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.api"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `api`.
    from api import database
    from api.security import get_current_user

from data.pipelines import queries, triggers

from .schemas import (
    PipelineRunAccepted,
    PipelineRunRequest,
    PipelineRunStatus,
    WeeklyWarehouseClientPerformance,
)


router = APIRouter(prefix="/reporting", tags=["reporting"])
logger = logging.getLogger("api.reporting")

TRIGGER_ROLES = {"admin", "manager"}
STORAGE_UNAVAILABLE = "Reporting storage unavailable"


def _engine():
    if database.engine is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=STORAGE_UNAVAILABLE)
    return database.engine


def _require_monday(week_start: date | None) -> None:
    if week_start is not None and week_start.weekday() != 0:
        raise HTTPException(
            status_code=422,
            detail="week_start debe ser un lunes (inicio de semana ISO).",
        )


@router.get(
    "/weekly-warehouse-client-performance",
    response_model=WeeklyWarehouseClientPerformance,
)
def get_weekly_warehouse_client_performance(
    _: Annotated[dict, Depends(get_current_user)],
    week_start: Annotated[
        date | None,
        Query(description="Lunes de la semana ISO (AAAA-MM-DD). Por defecto, la semana calculada más reciente."),
    ] = None,
) -> WeeklyWarehouseClientPerformance:
    """KPIs por almacén y cliente de una semana, con el contrato del BRIEFING."""
    _require_monday(week_start)
    engine = _engine()
    try:
        report = queries.get_weekly_performance(engine, week_start)
    except SQLAlchemyError:
        logger.exception("Reporting query failed for week_start=%s", week_start)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=STORAGE_UNAVAILABLE)
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay KPIs calculados para esa semana.")
    return WeeklyWarehouseClientPerformance.model_validate(report)


@router.get("/pipeline-runs/latest", response_model=PipelineRunStatus)
def get_latest_pipeline_run(
    _: Annotated[dict, Depends(get_current_user)],
) -> PipelineRunStatus:
    """Estado y metadata de la última corrida: inicio, fin, registros procesados y errores."""
    engine = _engine()
    try:
        run = queries.get_latest_pipeline_run(engine)
    except SQLAlchemyError:
        logger.exception("Reporting pipeline_runs query failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=STORAGE_UNAVAILABLE)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El pipeline todavía no ha corrido.")
    return PipelineRunStatus.model_validate(run)


@router.post(
    "/pipeline-runs",
    response_model=PipelineRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_pipeline_run(
    user: Annotated[dict, Depends(get_current_user)],
    body: PipelineRunRequest | None = None,
) -> PipelineRunAccepted:
    """Lanza una corrida manual en segundo plano (solo `admin` o `manager`)."""
    if user.get("role") not in TRIGGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo admin o manager pueden lanzar el pipeline.",
        )
    week_start = body.week_start if body else None
    _require_monday(week_start)
    engine = _engine()
    try:
        accepted = triggers.trigger_manual_run(
            engine, week_start=week_start, triggered_by=str(user.get("id"))
        )
    except triggers.PipelineRunAlreadyActiveError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": "Ya hay una corrida en marcha.", "active_run_id": str(exc.active_run_id)},
        )
    except SQLAlchemyError:
        logger.exception("Reporting manual trigger failed")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=STORAGE_UNAVAILABLE)
    logger.info("Pipeline manual run %s accepted (week_start=%s)", accepted.run_id, week_start)
    return PipelineRunAccepted(run_id=accepted.run_id, status=accepted.status, week_start=accepted.week_start)
