import logging
import os

from fastapi import APIRouter

from ..telemetry_schemas import TelemetryBatch


TELEMETRY_ENDPOINT = os.getenv(
    "TELEMETRY_ENDPOINT", "http://localhost:8000/telemetry/events"
)
# This value documents the expected endpoint pattern; it does not configure delivery.
router = APIRouter(prefix="/telemetry", tags=["telemetry"])
logger = logging.getLogger("api.timing")


@router.post("/events")
def receive_telemetry_events(batch: TelemetryBatch) -> dict[str, int]:
    logger.info(
        "Received %d telemetry events: %s",
        len(batch.events),
        [event.event_type for event in batch.events],
    )
    return {"received": len(batch.events)}
