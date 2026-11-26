"""Payloads de los eventos SSE de `/realtime/events`.

El `data:` de cada frame es **el JSON plano de estos modelos**, sin sobre
`{"event", "data"}`: el nombre del evento va en la línea `event:`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

EVENT_RESYNC = "resync"


class RfpTicketCreatedEvent(BaseModel):
    """`rfp_ticket_created`: un ticket clasificado como RFP válida que empieza a procesarse.

    Mismos nombres que el sistema de RFPs (`RfpTicketSummary`, `RfpMetadata`):
    `status` es `analizando`, `ticket_id` es entero y `client_country` es
    `"United States"` o `"Spain"`. `stage` y `original_filename` sirven para
    pintar la fila sin pedir el ticket.
    """

    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    rfp_id: str
    client_name: str | None = None
    client_country: str | None = None
    services_requested: list[str]
    status: str
    created_at: datetime
    stage: str | None = None
    original_filename: str | None = None


class ResyncEvent(BaseModel):
    """`resync`: el servidor no puede reenviar lo perdido; el cliente pide la lista una vez."""

    model_config = ConfigDict(extra="forbid")

    reason: str
