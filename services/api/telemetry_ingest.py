"""Validación por evento y mapeo a filas de `telemetry_events` (D35–D37, D41, D42).

El body del endpoint se acepta de forma laxa: `events` es una lista de items sin
tipar. Cada item se valida por separado con `TelemetryEvent.model_validate`, de
modo que un evento inválido se rechaza sin cancelar el resto del lote.
`TelemetryEvent` se reutiliza tal cual desde `telemetry_schemas.py`.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .telemetry_catalog import EVENT_CATALOG, TELEMETRY_SERVICE, EventContract
from .telemetry_schemas import TelemetryEvent


ENVELOPE_TAG_FIELDS = ("eventId", "sessionId", "userId", "schemaVersion", "requestId")


class TelemetryIngestEnvelope(BaseModel):
    """Envelope del lote: solo exige una lista `events` de hasta 50 items (D27)."""

    model_config = ConfigDict(extra="ignore")

    events: list[Any] = Field(max_length=50)


class TelemetryIngestResult(BaseModel):
    received: int
    stored: int
    rejected: int


def _numeric_value(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def event_to_row(event: TelemetryEvent, contract: EventContract) -> tuple[dict[str, Any], int]:
    """Mapea un evento válido a una fila. Devuelve la fila y las claves descartadas."""
    envelope = event.model_dump(mode="json", by_alias=True)
    properties = envelope["properties"]
    allowed = {
        key: value for key, value in properties.items() if key in contract.allowed_properties
    }
    tags = {**allowed, **{field: envelope[field] for field in ENVELOPE_TAG_FIELDS}}

    value = None
    if contract.value_property is not None:
        value = _numeric_value(properties.get(contract.value_property))

    row = {
        "timestamp": event.timestamp,
        "service": TELEMETRY_SERVICE,
        "event_type": event.event_type,
        "level": contract.level,
        "value": value,
        "message": contract.summary,
        "tags": tags,
    }
    return row, len(properties) - len(allowed)


def prepare_rows(raw_events: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """Valida cada item del lote.

    Devuelve las filas válidas, el diagnóstico de los rechazados (solo índice y
    códigos de error, nunca valores) y el número total de claves de `properties`
    descartadas por estar fuera del allowlist.
    """
    rows: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    dropped_keys = 0

    for index, raw in enumerate(raw_events):
        try:
            event = TelemetryEvent.model_validate(raw)
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False, include_context=False)
            rejections.append(
                {
                    "index": index,
                    "errors": [
                        {"type": error["type"], "loc": list(error["loc"])} for error in errors
                    ],
                }
            )
            continue

        contract = EVENT_CATALOG.get(event.event_type)
        if contract is None:
            rejections.append(
                {
                    "index": index,
                    "errors": [{"type": "unknown_event_type", "loc": ["event_type"]}],
                }
            )
            continue

        row, dropped = event_to_row(event, contract)
        rows.append(row)
        dropped_keys += dropped

    return rows, rejections, dropped_keys
