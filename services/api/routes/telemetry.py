import logging
import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from ..database import get_db
from ..telemetry_ingest import (
    TelemetryIngestEnvelope,
    TelemetryIngestResult,
    prepare_rows,
)
from ..telemetry_storage import bulk_insert_events


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
