"""Broker de eventos en memoria para el stream SSE (un solo proceso uvicorn).

* Una `asyncio.Queue(maxsize=100)` por suscriptor (cada conexión a
  `/realtime/events`), ligada al event loop en el que se suscribió.
* `publish()` es **thread-safe**: el pipeline de RFPs publica desde el
  threadpool de `BackgroundTasks`, así que la entrega se programa en el loop de
  cada suscriptor con `loop.call_soon_threadsafe`.
* Buffer circular de los últimos 200 eventos para el replay por
  `Last-Event-ID`. Los ids son `"{boot_id}-{seq}"` (`boot_id` = epoch de
  arranque): un id de otro arranque o ya fuera del buffer → `resync`.
* Un suscriptor con la cola llena se desconecta (el cliente se reconecta y
  recupera por replay o `resync`).
* Dedupe en servidor por `dedupe_key` (p. ej. un solo `rfp_ticket_created` por
  `ticket_id` en la vida del proceso).

Escalar a varios procesos (Redis pub/sub) se discute en `docs/realtime-sse/`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("api.realtime")

BUFFER_SIZE = 200
QUEUE_SIZE = 100
RETRY_MS = 3000

RESYNC_SERVER_RESTARTED = "server_restarted"
RESYNC_EVENTS_EXPIRED = "events_expired"
RESYNC_INVALID_ID = "invalid_last_event_id"

# Marca en la cola: el broker cierra esta conexión (cola llena).
CLOSE = object()


@dataclass(frozen=True)
class BrokerEvent:
    id: str
    seq: int
    event: str
    data: dict[str, Any]


@dataclass(eq=False)
class Subscription:
    """Una conexión: lo que hay que reenviar al abrir y la cola de lo que llegue después."""

    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop | None
    replay: list[BrokerEvent] = field(default_factory=list)
    resync: str | None = None
    cursor_id: str = ""  # id de la posición actual (para el frame de apertura o el `resync`)
    closed: bool = False

    def deliver(self, item: Any) -> None:
        """Mete un evento en la cola; si está llena, vacía la cola y deja solo `CLOSE`. Corre en `loop`."""
        if self.closed:
            return
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.closed = True
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(CLOSE)
            logger.warning("Suscriptor SSE desconectado: cola llena (%d eventos)", self.queue.maxsize)


class EventBroker:
    def __init__(self, *, buffer_size: int = BUFFER_SIZE, queue_size: int = QUEUE_SIZE, boot_id: str | None = None):
        self.boot_id = boot_id or str(int(time.time()))
        self.queue_size = queue_size
        self._seq = 0
        self._buffer: deque[BrokerEvent] = deque(maxlen=buffer_size)
        self._subscribers: set[Subscription] = set()
        self._seen_keys: set[str] = set()
        self._lock = threading.Lock()

    # ── publicación ─────────────────────────────────────────────────────────
    def publish(self, event: str, data: dict[str, Any], *, dedupe_key: str | None = None) -> BrokerEvent | None:
        """Guarda el evento en el buffer y lo entrega a cada suscriptor. `None` si es un duplicado."""
        with self._lock:
            if dedupe_key is not None:
                if dedupe_key in self._seen_keys:
                    logger.info("Evento %s duplicado (%s): no se reenvía", event, dedupe_key)
                    return None
                self._seen_keys.add(dedupe_key)
            self._seq += 1
            item = BrokerEvent(id=self._event_id(self._seq), seq=self._seq, event=event, data=dict(data))
            self._buffer.append(item)
            subscribers = list(self._subscribers)
        for subscription in subscribers:
            self._schedule(subscription, item)
        return item

    @staticmethod
    def _schedule(subscription: Subscription, item: Any) -> None:
        loop = subscription.loop
        if loop is None or loop.is_closed():
            subscription.deliver(item)
            return
        try:
            loop.call_soon_threadsafe(subscription.deliver, item)
        except RuntimeError:  # el loop se cerró entre la comprobación y la llamada
            subscription.deliver(item)

    # ── suscripción ─────────────────────────────────────────────────────────
    def subscribe(self, last_event_id: str | None = None) -> Subscription:
        """Registra una conexión y calcula, de forma atómica con `publish`, qué reenviar.

        Sin `Last-Event-ID`: nada que reenviar. Con un id de este arranque aún en
        el buffer: los eventos posteriores. Si no (otro arranque, fuera del
        buffer, mal formado): `resync` con su motivo.
        """
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        subscription = Subscription(queue=asyncio.Queue(maxsize=self.queue_size), loop=loop)
        with self._lock:
            subscription.cursor_id = self._event_id(self._seq)
            if last_event_id:
                subscription.replay, subscription.resync = self._replay_after(last_event_id.strip())
            self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscribers.discard(subscription)
        subscription.closed = True

    def _replay_after(self, last_event_id: str) -> tuple[list[BrokerEvent], str | None]:
        boot_id, _, raw_seq = last_event_id.rpartition("-")
        if not boot_id or not raw_seq.isdigit():
            return [], RESYNC_INVALID_ID
        if boot_id != self.boot_id:
            return [], RESYNC_SERVER_RESTARTED
        seq = int(raw_seq)
        if seq > self._seq:
            return [], RESYNC_INVALID_ID
        oldest = self._buffer[0].seq if self._buffer else self._seq + 1
        if seq + 1 < oldest:
            return [], RESYNC_EVENTS_EXPIRED
        return [item for item in self._buffer if item.seq > seq], None

    # ── utilidades ──────────────────────────────────────────────────────────
    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    def _event_id(self, seq: int) -> str:
        return f"{self.boot_id}-{seq}"


def format_sse(event: str, data: dict[str, Any], *, event_id: str | None = None) -> str:
    """Un frame SSE: `id:` (opcional), `event:` y **una sola** línea `data:` con JSON plano."""
    lines = []
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}")
    return "\n".join(lines) + "\n\n"


def format_open(*, retry_ms: int = RETRY_MS, event_id: str | None = None) -> str:
    """Frame de apertura: `retry:`, el id actual (si se da, sin despachar evento) y `: connected`."""
    lines = [f"retry: {retry_ms}"]
    if event_id:
        lines.append(f"id: {event_id}")
    lines.append(": connected")
    return "\n".join(lines) + "\n\n"


def format_comment(text: str) -> str:
    return f": {text}\n\n"


broker = EventBroker()


def get_broker() -> EventBroker:
    """Dependencia FastAPI (sobreescribible en tests)."""
    return broker
