"""`GET /realtime/events`: stream SSE de eventos de negocio, protegido con el JWT del backoffice.

Wire (una sola línea `data:` con JSON plano, sin sobre `{"event", "data"}`)::

    retry: 3000
    id: <boot>-<seq>          ← solo en conexiones nuevas: posición actual
    : connected

    id: 1764160000-7
    event: rfp_ticket_created
    data: {"ticket_id":42,"rfp_id":"RFP-…","client_name":"…","status":"analizando",…}

    : keep-alive              ← cada SSE_KEEPALIVE_SECONDS sin eventos

Recuperación: el cliente reenvía `Last-Event-ID` al reconectar y recibe los
eventos posteriores del buffer; si no se puede (otro arranque, fuera del
buffer) recibe `event: resync` y pide `GET /rfp/tickets` una vez.

El endpoint es genérico (cualquier nombre de evento del broker). Importar este
módulo registra el broker como listener del pipeline de RFPs. Sin llamadas a
modelos ni agentes.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Annotated, Any, AsyncIterator

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.api.security import get_current_user
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.api"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `api`.
    from api.security import get_current_user

from data.pipelines.rfp_intake import events as pipeline_events

from .broker import (
    CLOSE,
    RETRY_MS,
    EventBroker,
    format_comment,
    format_open,
    format_sse,
    get_broker,
)
from .schemas import EVENT_RESYNC, ResyncEvent, RfpTicketCreatedEvent

router = APIRouter(prefix="/realtime", tags=["realtime"])
logger = logging.getLogger("api.realtime")

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@dataclass(frozen=True)
class StreamSettings:
    keepalive_seconds: float = 15.0
    # Solo tests: tras el replay, sigue entregando lo pendiente y cierra cuando
    # la cola pasa un intervalo de keep-alive vacía (emite ese `: keep-alive`).
    close_after_replay: bool = False


def get_stream_settings() -> StreamSettings:
    return StreamSettings(keepalive_seconds=float(os.getenv("SSE_KEEPALIVE_SECONDS", "15")))


# ── pipeline → broker ───────────────────────────────────────────────────────
def forward_pipeline_event(event: str, payload: dict[str, Any]) -> None:
    """Listener del pipeline: valida el payload y lo publica (un aviso por `ticket_id`)."""
    if event != pipeline_events.EVENT_RFP_TICKET_CREATED:
        return
    data = RfpTicketCreatedEvent.model_validate(payload).model_dump(mode="json")
    published = get_broker().publish(event, data, dedupe_key=f"{event}:{data['ticket_id']}")
    if published is not None:
        logger.info("SSE %s ticket %s → %s", event, data["ticket_id"], published.id)


pipeline_events.subscribe(forward_pipeline_event)


# ── stream ──────────────────────────────────────────────────────────────────
async def _event_stream(broker: EventBroker, settings: StreamSettings, last_event_id: str | None) -> AsyncIterator[str]:
    subscription = broker.subscribe(last_event_id)
    try:
        fresh = not last_event_id
        yield format_open(retry_ms=RETRY_MS, event_id=subscription.cursor_id if fresh else None)
        if subscription.resync:
            yield format_sse(
                EVENT_RESYNC, ResyncEvent(reason=subscription.resync).model_dump(), event_id=subscription.cursor_id
            )
        for item in subscription.replay:
            yield format_sse(item.event, item.data, event_id=item.id)
        while True:
            try:
                item = await asyncio.wait_for(subscription.queue.get(), timeout=settings.keepalive_seconds)
            except TimeoutError:
                yield format_comment("keep-alive")
                if settings.close_after_replay:
                    return
                continue
            if item is CLOSE:
                return
            yield format_sse(item.event, item.data, event_id=item.id)
    finally:
        broker.unsubscribe(subscription)


@router.get(
    "/events",
    response_class=StreamingResponse,
    response_model=None,
    summary="Stream SSE de eventos en tiempo real (rfp_ticket_created)",
    responses={200: {"content": {"text/event-stream": {}}}, 401: {"description": "Sin JWT válido"}},
)
async def stream_realtime_events(
    _user: Annotated[dict, Depends(get_current_user)],
    broker: Annotated[EventBroker, Depends(get_broker)],
    settings: Annotated[StreamSettings, Depends(get_stream_settings)],
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(broker, settings, last_event_id),
        media_type="text/event-stream; charset=utf-8",
        headers=SSE_HEADERS,
    )
