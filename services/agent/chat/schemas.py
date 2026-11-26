"""Contratos del chat por WebSocket: la sesión, los mensajes y cada evento del sobre `{"event", "data"}`.

Nombres del BRIEFING de la Parte 2 (`ChatSession`, `session_id`, `agent_id = first_line_cx`,
`token_chunk`, `interrupt_requested`, `generation_interrupted`, `generation_completed`,
`session_snapshot`, `user_message`). Añadidos necesarios y documentados:
`generation_started`, `chat_error` y `message_id` en `token_chunk`. Todo `data` lleva `session_id`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..schemas import AgentQueryResponse

AGENT_ID = "first_line_cx"
CLIENT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,40}$"
MAX_MESSAGE_CHARS = 500
INTERRUPT_WAIT_SECONDS = 5.0

SessionStatus = Literal["active", "interrupted", "closed"]
MessageRole = Literal["user", "assistant"]
MessageStatus = Literal["streaming", "completed", "interrupted", "error"]
# Mismos valores que la respuesta de `POST /agent/query`: no se inventa otro vocabulario.
AgentStatus = AgentQueryResponse.model_fields["status"].annotation
AgentSource = Literal["incidents", "inventory", "rag"]
ChatErrorCode = Literal[
    "invalid_message", "generation_in_progress", "nothing_to_interrupt", "forbidden", "agent_unavailable"
]

# Nombres de evento.
EVENT_SESSION_SNAPSHOT = "session_snapshot"
EVENT_USER_MESSAGE = "user_message"
EVENT_INTERRUPT_REQUESTED = "interrupt_requested"
EVENT_GENERATION_STARTED = "generation_started"
EVENT_TOKEN_CHUNK = "token_chunk"
EVENT_GENERATION_INTERRUPTED = "generation_interrupted"
EVENT_GENERATION_COMPLETED = "generation_completed"
EVENT_CHAT_ERROR = "chat_error"
CLIENT_EVENTS = (EVENT_USER_MESSAGE, EVENT_INTERRUPT_REQUESTED)


def new_session_id() -> str:
    return "chat_" + uuid.uuid4().hex[:12]


def new_message_id() -> str:
    return "msg_" + uuid.uuid4().hex[:12]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# Entidades
# --------------------------------------------------------------------------- #
class ChatSessionCreate(_Strict):
    client_id: str = Field(pattern=CLIENT_ID_PATTERN, description="Cliente (marca) al que pertenece la conversación.")


class ChatSession(_Strict):
    """`ChatSession` del BRIEFING: la conversación del cliente con el First-line CX agent."""

    session_id: str
    agent_id: Literal["first_line_cx"] = AGENT_ID
    user_id: int = Field(description="Usuario del JWT que chatea (el dueño de la sesión).")
    client_id: str
    status: SessionStatus
    created_at: datetime


class ChatMessage(_Strict):
    message_id: str
    session_id: str
    role: MessageRole
    text: str
    status: MessageStatus
    run_id: str | None = None
    created_at: datetime
    updated_at: datetime


class ActiveGeneration(_Strict):
    """La respuesta en curso: lo ya emitido y el `sequence` del último `token_chunk`."""

    message_id: str
    text: str
    sequence: int = Field(ge=0)


# --------------------------------------------------------------------------- #
# Cliente → servidor
# --------------------------------------------------------------------------- #
def _clean_text(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class ClientEnvelope(_Strict):
    event: Literal["user_message", "interrupt_requested"]
    data: dict[str, Any]


class UserMessageIn(_Strict):
    session_id: str
    text: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)

    _strip = field_validator("text", mode="before")(_clean_text)


class InterruptRequestedIn(_Strict):
    session_id: str
    new_input: str | None = Field(default=None, max_length=MAX_MESSAGE_CHARS)

    @field_validator("new_input", mode="before")
    @classmethod
    def _blank_is_none(cls, value: Any) -> Any:
        value = _clean_text(value)
        return value or None


# --------------------------------------------------------------------------- #
# Servidor → cliente
# --------------------------------------------------------------------------- #
class SessionSnapshotData(_Strict):
    session_id: str
    session: ChatSession
    messages: list[ChatMessage]
    active_generation: ActiveGeneration | None = None


class UserMessageData(_Strict):
    session_id: str
    message_id: str
    text: str
    created_at: datetime


class GenerationStartedData(_Strict):
    session_id: str
    message_id: str


class TokenChunkData(_Strict):
    session_id: str
    message_id: str
    token: str
    sequence: int = Field(ge=1, description="Empieza en 1 en cada mensaje del asistente.")


class GenerationInterruptedData(_Strict):
    session_id: str
    message_id: str
    status: Literal["interrupted"] = "interrupted"


class GenerationCompletedData(_Strict):
    session_id: str
    message_id: str
    answer: str = Field(description="Respuesta final ya pasada por la guardia de salida: la UI la deja como definitiva.")
    status: AgentStatus  # type: ignore[valid-type]
    sources: list[AgentSource]


class ChatErrorData(_Strict):
    session_id: str
    code: ChatErrorCode
    detail: str
    message_id: str | None = None


def dump_event(name: str, data: BaseModel) -> dict[str, Any]:
    """Sobre `{"event", "data"}` listo para `send_json` (fechas en ISO 8601)."""
    return {"event": name, "data": data.model_dump(mode="json")}
