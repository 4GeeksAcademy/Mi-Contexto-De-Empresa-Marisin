"""Pub/sub en memoria del chat: un canal `chat.<session_id>` por sesión (un solo proceso uvicorn).

* El productor (el `ChatTurnManager`, con el agente generando en un hilo) publica
  sin saber cuántas conexiones hay; cada conexión WebSocket es un suscriptor con
  su `asyncio.Queue(maxsize=1000)`, ligada al event loop en el que se suscribió.
* `publish()` es **thread-safe**: la entrega se programa en el loop de cada
  suscriptor con `loop.call_soon_threadsafe` y respeta el orden de publicación.
* Un suscriptor con la cola llena se cierra (marca `CLOSE`): el WebSocket se
  cierra con 1013 y el cliente reconecta y rehidrata con `session_snapshot`.

Independiente del `EventBroker` SSE de `services/realtime/` (Parte 1). Escalar a
varios procesos (Redis pub/sub y afinidad de sesión) se discute en `docs/agent-chat-ws/`.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("api.agent.chat")

QUEUE_SIZE = 1000
CLOSE_QUEUE_FULL = 1013  # «Try Again Later»: el cliente reconecta y recibe un snapshot nuevo

# Marca en la cola: el pub/sub cierra esta conexión (cola llena).
CLOSE = object()


def channel_name(session_id: str) -> str:
    return f"chat.{session_id}"


@dataclass(eq=False)
class ChatSubscription:
    channel: str
    queue: asyncio.Queue
    loop: asyncio.AbstractEventLoop | None
    closed: bool = False

    def deliver(self, item: Any) -> None:
        """Mete un evento en la cola; si está llena, la vacía y deja solo `CLOSE`. Corre en `loop`."""
        if self.closed:
            return
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.closed = True
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(CLOSE)
            logger.warning("Suscriptor de %s cerrado: cola llena (%d eventos)", self.channel, self.queue.maxsize)


class ChatPubSub:
    def __init__(self, *, queue_size: int = QUEUE_SIZE):
        self.queue_size = queue_size
        self._channels: dict[str, set[ChatSubscription]] = {}
        self._lock = threading.Lock()

    def subscribe(self, session_id: str) -> ChatSubscription:
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        channel = channel_name(session_id)
        subscription = ChatSubscription(channel=channel, queue=asyncio.Queue(maxsize=self.queue_size), loop=loop)
        with self._lock:
            self._channels.setdefault(channel, set()).add(subscription)
        return subscription

    def unsubscribe(self, subscription: ChatSubscription) -> None:
        with self._lock:
            subscribers = self._channels.get(subscription.channel)
            if subscribers is not None:
                subscribers.discard(subscription)
                if not subscribers:
                    del self._channels[subscription.channel]
        subscription.closed = True

    def publish(self, session_id: str, event: dict[str, Any]) -> int:
        """Entrega `event` a cada suscriptor del canal de la sesión; devuelve a cuántos."""
        with self._lock:
            subscribers = list(self._channels.get(channel_name(session_id), ()))
        for subscription in subscribers:
            self._schedule(subscription, event)
        return len(subscribers)

    @staticmethod
    def _schedule(subscription: ChatSubscription, item: Any) -> None:
        loop = subscription.loop
        if loop is None or loop.is_closed():
            subscription.deliver(item)
            return
        try:
            loop.call_soon_threadsafe(subscription.deliver, item)
        except RuntimeError:  # el loop se cerró entre la comprobación y la llamada
            subscription.deliver(item)

    def subscriber_count(self, session_id: str) -> int:
        with self._lock:
            return len(self._channels.get(channel_name(session_id), ()))
