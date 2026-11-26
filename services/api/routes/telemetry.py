from datetime import datetime, timezone
import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from .. import database
from ..security import require_staff
from ..cache import CACHE_ENABLED, TELEMETRY_REPORT_TTL, telemetry_report_cache
from ..database import get_db
from ..telemetry_ingest import (
    TelemetryIngestEnvelope,
    TelemetryIngestResult,
    prepare_rows,
)
from ..telemetry_report import (
    ReportPeriodError,
    TelemetryReport,
    report_cache_key,
    resolve_period,
)
from ..telemetry_storage import bulk_insert_events

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.telemetry import analysis
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.telemetry"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `telemetry`.
    from telemetry import analysis


TELEMETRY_ENDPOINT = os.getenv(
    "TELEMETRY_ENDPOINT", "http://localhost:8000/telemetry/events"
)
# This value documents the expected endpoint pattern; it does not configure delivery.
router = APIRouter(prefix="/telemetry", tags=["telemetry"])
logger = logging.getLogger("api.timing")


@router.post("/events", response_model=TelemetryIngestResult)
def receive_telemetry_events(
    envelope: TelemetryIngestEnvelope,
    session: Annotated[Session, Depends(get_db)],
) -> TelemetryIngestResult:
    """Valida cada evento por separado y guarda los válidos en un único INSERT.

    Un evento inválido se cuenta en `rejected` sin cancelar el resto del lote.
    Si falla la base de datos no se guarda nada y se responde 503, para que el
    cliente reintente el lote completo.
    """
    received = len(envelope.events)
    rows, rejections, dropped_keys = prepare_rows(envelope.events)

    stored = 0
    if rows:
        try:
            stored = bulk_insert_events(session, rows)
        except SQLAlchemyError:
            session.rollback()
            logger.exception(
                "Telemetry storage failed for %d valid events; nothing stored", len(rows)
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Telemetry storage unavailable",
            )

    logger.info(
        "Telemetry batch: received=%d stored=%d rejected=%d dropped_property_keys=%d types=%s",
        received,
        stored,
        len(rejections),
        dropped_keys,
        [row["event_type"] for row in rows],
    )
    if rejections:
        logger.info("Telemetry rejected events: %s", rejections)

    return TelemetryIngestResult(received=received, stored=stored, rejected=len(rejections))


@router.get("/report", response_model=TelemetryReport)
def get_telemetry_report(
    _: Annotated[dict, Depends(require_staff)],  # solo personal (D8); POST /events sigue público
    start_date: Annotated[
        datetime | None,
        Query(description="Inicio inclusivo, ISO 8601. Sin zona horaria se interpreta como UTC."),
    ] = None,
    end_date: Annotated[
        datetime | None,
        Query(description="Fin exclusivo, ISO 8601. Por defecto, ahora (UTC)."),
    ] = None,
) -> TelemetryReport:
    """Reporte técnico de la telemetría: volumen, errores, latencia y login.

    La ventana se resuelve una sola vez (por defecto, los últimos 7 días) y se
    pasa a cada métrica. El resultado se guarda 60 s en caché por ventana: dentro
    de ese tiempo, la misma ventana no vuelve a ejecutar el pipeline.
    """
    try:
        start, end = resolve_period(start_date, end_date, now=datetime.now(timezone.utc))
    except ReportPeriodError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    cache_key = report_cache_key(start, end)
    if CACHE_ENABLED:
        hit, cached = telemetry_report_cache.get(cache_key)
        if hit:
            return cached

    if database.engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telemetry storage unavailable",
        )
    try:
        metrics = analysis.build_report_metrics(start, end, database.engine)
    except SQLAlchemyError:
        logger.exception("Telemetry report failed for %s – %s", start.isoformat(), end.isoformat())
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telemetry storage unavailable",
        )

    report = TelemetryReport.model_validate(
        {"period": {"from": start, "to": end}, "metrics": metrics}
    )
    if CACHE_ENABLED:
        telemetry_report_cache.set(cache_key, report, ttl=TELEMETRY_REPORT_TTL)
    logger.info(
        "Telemetry report computed for %s – %s", start.isoformat(), end.isoformat()
    )
    return report
