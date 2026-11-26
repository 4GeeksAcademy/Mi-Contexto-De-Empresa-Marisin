"""Chat del First-line CX agent: `POST /agent/chat/sessions` y el WebSocket de la sesión.

* `POST /agent/chat/sessions` `{client_id}` → 201 `ChatSession` (dueño = usuario del JWT).
* `WS /agent/chat/sessions/{session_id}/ws?token=<JWT>` — el mismo JWT del
  backoffice (los navegadores no permiten `Authorization` en el handshake).

Orden al conectar: auth → sesión → suscribirse a `chat.<session_id>` **primero**
→ historial + respuesta en curso → `session_snapshot` antes que nada → reenviar
la cola (sin los `token_chunk` que el snapshot ya incluye). Sin sesión válida se
acepta y se cierra con un código propio y **sin enviar ningún evento**, para que
el navegador lo reciba y el cliente no reintente: 4401 (sin token o inválido),
4404 (sesión inexistente), 4403 (ni dueño ni `admin`/`manager`). Sin PostgreSQL:
`POST` → 503 y el WS cierra con 1011. Cola llena → 1013 (el cliente rehidrata).

El handler nunca llama al agente: solo pasa comandos al `ChatTurnManager` y
escribe en su socket lo que llega a su cola. Solo el dueño escribe; `admin` y
`manager` pueden observar (reciben `chat_error forbidden` si envían algo).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.api.database import engine
    from services.api.security import get_current_user
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.api"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `api`.
    from api.database import engine
    from api.security import get_current_user

from . import logging_filters
from .pubsub import CLOSE, CLOSE_QUEUE_FULL, ChatSubscription
from .schemas import (
    EVENT_CHAT_ERROR,
    EVENT_GENERATION_STARTED,
    EVENT_SESSION_SNAPSHOT,
    EVENT_TOKEN_CHUNK,
    EVENT_USER_MESSAGE,
    MAX_MESSAGE_CHARS,
    ChatErrorData,
    ChatSession,
    ChatSessionCreate,
    ClientEnvelope,
    InterruptRequestedIn,
    SessionSnapshotData,
    UserMessageIn,
    dump_event,
)
from .store import ChatStore, SqlChatStore
from .turns import (
    AGENT_UNAVAILABLE,
    ChatTurnManager,
    GenerationInProgress,
    NothingToInterrupt,
    TurnRunner,
    get_turn_manager,
    get_turn_runner,
)

logging_filters.install()  # el JWT de `?token=` nunca llega a los logs de uvicorn

router = APIRouter(prefix="/chat", tags=["agent-chat"])
logger = logging.getLogger("api.agent.chat")

OBSERVER_ROLES = {"admin", "manager"}
DATABASE_UNAVAILABLE = "El chat de soporte necesita PostgreSQL (DATABASE_URL de Supabase en .env)."

CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404
CLOSE_UNAVAILABLE = 1011


def get_chat_store() -> ChatStore | None:
    """Dependencia FastAPI (sobreescribible en tests con `InMemoryChatStore`). `None` sin PostgreSQL."""
    return SqlChatStore(engine) if engine is not None else None


@router.post("/sessions", response_model=ChatSession, status_code=status.HTTP_201_CREATED)
def create_chat_session(
    body: ChatSessionCreate,
    user: Annotated[dict, Depends(get_current_user)],
    store: Annotated[ChatStore | None, Depends(get_chat_store)],
) -> ChatSession:
    """Abre una conversación del usuario con el First-line CX agent."""
    if store is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DATABASE_UNAVAILABLE)
    session = store.create_session(user_id=int(user["id"]), client_id=body.client_id)
    logger.info("chat session=%s creada user_id=%s client_id=%s", session.session_id, session.user_id, session.client_id)
    return session


async def authenticate(token: str | None) -> dict | None:
    """El mismo JWT que la API del backoffice; `None` si falta o no es válido."""
    if not token:
        return None
    try:
        return await run_in_threadpool(get_current_user, token)
    except HTTPException:
        return None


async def refuse(websocket: WebSocket, code: int, reason: str) -> None:
    await websocket.accept()
    await websocket.close(code=code, reason=reason)


@router.websocket("/sessions/{session_id}/ws")
async def chat_socket(
    websocket: WebSocket,
    session_id: str,
    store: Annotated[ChatStore | None, Depends(get_chat_store)],
    turn_runner: Annotated[TurnRunner, Depends(get_turn_runner)],
    manager: Annotated[ChatTurnManager, Depends(get_turn_manager)],
    token: Annotated[str | None, Query()] = None,
) -> None:
    user = await authenticate(token)
    if user is None:
        await refuse(websocket, CLOSE_UNAUTHORIZED, "unauthorized")
        return
    if store is None:
        await refuse(websocket, CLOSE_UNAVAILABLE, "chat store unavailable")
        return
    try:
        session = await run_in_threadpool(store.get_session, session_id)
    except Exception:
        logger.exception("chat session=%s: no se pudo leer la sesión", session_id)
        await refuse(websocket, CLOSE_UNAVAILABLE, "chat store unavailable")
        return
    if session is None:
        await refuse(websocket, CLOSE_NOT_FOUND, "session not found")
        return
    is_owner = session.user_id == int(user["id"])
    if not is_owner and user.get("role") not in OBSERVER_ROLES:
        await refuse(websocket, CLOSE_FORBIDDEN, "forbidden")
        return

    await websocket.accept()
    subscription = manager.pubsub.subscribe(session_id)  # antes del snapshot: sin huecos
    try:
        try:
            snapshot = await manager.snapshot(session_id, store)
        except Exception:
            logger.exception("chat session=%s: no se pudo rehidratar", session_id)
            await websocket.close(code=CLOSE_UNAVAILABLE, reason="chat store unavailable")
            return
        await websocket.send_json(dump_event(EVENT_SESSION_SNAPSHOT, snapshot))
        logger.info("chat session=%s conectado user_id=%s %s mensajes=%d en_curso=%s", session_id, user["id"],
                    "dueño" if is_owner else "observador", len(snapshot.messages),
                    snapshot.active_generation.message_id if snapshot.active_generation else None)

        sender = asyncio.create_task(forward_events(websocket, subscription, snapshot))
        receiver = asyncio.create_task(receive_commands(
            websocket, subscription, session_id=session_id, user=user, is_owner=is_owner,
            store=store, turn_runner=turn_runner, manager=manager,
        ))
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            error = task.exception()
            if error is not None and not isinstance(error, WebSocketDisconnect):
                logger.error("chat session=%s: la conexión terminó con %r", session_id, error)
    finally:
        manager.pubsub.unsubscribe(subscription)
        logger.info("chat session=%s desconectado user_id=%s", session_id, user["id"])


def already_in_snapshot(item: dict[str, Any], snapshot: SessionSnapshotData, known_ids: set[str]) -> bool:
    """Eventos de la ventana de reconexión que el snapshot ya contiene (sin duplicados)."""
    data = item.get("data") or {}
    event = item.get("event")
    if event == EVENT_TOKEN_CHUNK:
        active = snapshot.active_generation
        return active is not None and data.get("message_id") == active.message_id \
            and data.get("sequence", 0) <= active.sequence
    if event in (EVENT_USER_MESSAGE, EVENT_GENERATION_STARTED):
        return data.get("message_id") in known_ids
    return False


async def forward_events(websocket: WebSocket, subscription: ChatSubscription, snapshot: SessionSnapshotData) -> None:
    """Único escritor del socket: reenvía la cola del canal (y las respuestas privadas a esta conexión)."""
    known_ids = {message.message_id for message in snapshot.messages}
    while True:
        item = await subscription.queue.get()
        if item is CLOSE:
            await websocket.close(code=CLOSE_QUEUE_FULL, reason="queue full")
            return
        if already_in_snapshot(item, snapshot, known_ids):
            continue
        await websocket.send_json(item)


def chat_error(session_id: str, code: str, detail: str, message_id: str | None = None) -> dict[str, Any]:
    return dump_event(EVENT_CHAT_ERROR, ChatErrorData(session_id=session_id, code=code, detail=detail,
                                                      message_id=message_id))


async def receive_commands(websocket: WebSocket, subscription: ChatSubscription, **context: Any) -> None:
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        reply = await handle_command(message.get("text"), **context)
        if reply is not None:
            subscription.deliver(reply)  # por la misma cola: un solo escritor y en orden


def _parse(model: type[BaseModel], data: dict[str, Any], session_id: str) -> tuple[Any, dict | None]:
    try:
        parsed = model.model_validate(data)
    except ValidationError:
        return None, chat_error(session_id, "invalid_message",
                                f"El texto debe tener entre 1 y {MAX_MESSAGE_CHARS} caracteres.")
    if parsed.session_id != session_id:
        return None, chat_error(session_id, "invalid_message", "El session_id no coincide con el de la conexión.")
    return parsed, None


async def handle_command(
    text: str | None, *, session_id: str, user: dict, is_owner: bool, store: ChatStore,
    turn_runner: TurnRunner, manager: ChatTurnManager,
) -> dict[str, Any] | None:
    """Un frame del cliente → comando al gestor de turnos; devuelve el `chat_error` privado, si hay."""
    try:
        envelope = ClientEnvelope.model_validate(json.loads(text or ""))
    except (ValueError, ValidationError):
        return chat_error(session_id, "invalid_message",
                          'Se espera {"event": "user_message" | "interrupt_requested", "data": {...}}.')
    if not is_owner:
        return chat_error(session_id, "forbidden", "Solo el dueño de la sesión puede escribir: estás observando.")

    try:
        if envelope.event == EVENT_USER_MESSAGE:
            command, error = _parse(UserMessageIn, envelope.data, session_id)
            if error:
                return error
            # shield: si la conexión se cierra a mitad, el turno queda en un estado coherente
            await asyncio.shield(manager.start_turn(session_id, command.text, user=user, store=store,
                                                    turn_runner=turn_runner))
        else:
            command, error = _parse(InterruptRequestedIn, envelope.data, session_id)
            if error:
                return error
            await asyncio.shield(manager.interrupt(session_id, command.new_input, user=user, store=store,
                                                   turn_runner=turn_runner))
    except GenerationInProgress as exc:
        return chat_error(session_id, "generation_in_progress",
                          "Ya hay una respuesta en curso: para redirigirla usa interrupt_requested.", exc.message_id)
    except NothingToInterrupt:
        return chat_error(session_id, "nothing_to_interrupt", "No hay ninguna respuesta en curso que interrumpir.")
    except Exception:
        logger.exception("chat session=%s: fallo al procesar %s", session_id, envelope.event)
        return chat_error(session_id, "agent_unavailable", AGENT_UNAVAILABLE)
    return None
