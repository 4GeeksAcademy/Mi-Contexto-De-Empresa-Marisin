"""Gancho de eventos del pipeline de RFPs (notificaciones en tiempo real).

El pipeline no conoce FastAPI ni `services.*`: solo llama a `emit()`. Quien
quiera enterarse (el broker SSE de `services/realtime/`) se registra con
`subscribe()` al importarse. Sin listeners, `emit()` no hace nada (por ejemplo,
`scripts/rfp_intake_run.py` en su propio proceso).

`emit()` **nunca lanza**: un listener que falla se registra en el log y el
pipeline sigue. Aquí no hay llamadas a modelos ni agentes.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger("rfp_intake.events")

EVENT_RFP_TICKET_CREATED = "rfp_ticket_created"

Listener = Callable[[str, dict[str, Any]], None]

_listeners: list[Listener] = []
_lock = threading.Lock()


def subscribe(listener: Listener) -> Callable[[], None]:
    """Registra `listener(event, payload)`; idempotente. Devuelve la función para darlo de baja."""
    with _lock:
        if listener not in _listeners:
            _listeners.append(listener)
    return lambda: unsubscribe(listener)


def unsubscribe(listener: Listener) -> None:
    with _lock:
        if listener in _listeners:
            _listeners.remove(listener)


def emit(event: str, payload: dict[str, Any]) -> None:
    """Entrega el evento a cada listener; un fallo de uno no afecta a los demás ni al pipeline."""
    with _lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(event, dict(payload))
        except Exception:
            logger.exception("El listener %r falló con el evento %s", listener, event)


def _iso_utc(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:  # la base de datos guarda UTC sin zona
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return str(value) if value is not None else None


def ticket_created_payload(ticket: dict[str, Any]) -> dict[str, Any]:
    """Campos de `rfp_ticket_created` a partir del ticket de `store.get_ticket()` (con sus metadatos).

    Mismos nombres que el sistema de RFPs; nada del documento ni de las secciones.
    """
    metadata = ticket.get("metadata") or {}
    return {
        "ticket_id": ticket["ticket_id"],
        "rfp_id": ticket["rfp_id"],
        "client_name": metadata.get("client_name"),
        "client_country": metadata.get("client_country"),
        "services_requested": list(metadata.get("services_requested") or []),
        "status": ticket["status"],
        "created_at": _iso_utc(ticket.get("created_at")),
        "stage": ticket.get("stage"),
        "original_filename": ticket.get("original_filename"),
    }
