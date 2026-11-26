"""Persistencia de las sesiones y los mensajes del chat (fuente de la rehidratación).

* `SqlChatStore` — PostgreSQL (Supabase) con SQLModel, como las RFPs. Tablas
  `chat_sessions` y `chat_messages`; DDL idempotente con checks, índice y RLS en
  `services/sql/006_chat_sessions.sql` (`SQLModel.metadata.create_all` al
  arrancar también las crea, sin los checks).
* `InMemoryChatStore` — misma semántica en diccionarios, para los tests.

El historial vive aquí y no en el checkpointer de LangGraph: el `thread_id` de
cada corrida sigue siendo su `run_id` (el estado del grafo no es historial).
Todos los métodos son síncronos; el WebSocket los llama con `run_in_threadpool`.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Optional, Protocol

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, select

from .schemas import (
    AGENT_ID,
    ChatMessage,
    ChatSession,
    MessageRole,
    MessageStatus,
    SessionStatus,
    new_message_id,
    new_session_id,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SessionNotFound(LookupError):
    def __init__(self, session_id: str):
        super().__init__(f"La sesión de chat {session_id} no existe")
        self.session_id = session_id


class MessageNotFound(LookupError):
    def __init__(self, message_id: str):
        super().__init__(f"El mensaje {message_id} no existe")
        self.message_id = message_id


class ChatStore(Protocol):
    def create_session(self, *, user_id: int, client_id: str) -> ChatSession: ...

    def get_session(self, session_id: str) -> ChatSession | None: ...

    def set_session_status(self, session_id: str, status: SessionStatus) -> ChatSession: ...

    def add_message(
        self, *, session_id: str, role: MessageRole, text: str, status: MessageStatus,
        message_id: str | None = None, run_id: str | None = None,
    ) -> ChatMessage: ...

    def update_message(
        self, message_id: str, *, text: str | None = None, status: MessageStatus | None = None,
        run_id: str | None = None,
    ) -> ChatMessage: ...

    def list_messages(self, session_id: str) -> list[ChatMessage]: ...


# --------------------------------------------------------------------------- #
# En memoria (tests)
# --------------------------------------------------------------------------- #
class InMemoryChatStore:
    """Misma semántica que `SqlChatStore`; los mensajes quedan en orden de creación."""

    def __init__(self) -> None:
        self.sessions: dict[str, ChatSession] = {}
        self.messages: dict[str, ChatMessage] = {}
        self._lock = threading.Lock()

    def create_session(self, *, user_id: int, client_id: str) -> ChatSession:
        session = ChatSession(session_id=new_session_id(), agent_id=AGENT_ID, user_id=user_id,
                              client_id=client_id, status="active", created_at=utc_now())
        with self._lock:
            self.sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str) -> ChatSession | None:
        with self._lock:
            return self.sessions.get(session_id)

    def set_session_status(self, session_id: str, status: SessionStatus) -> ChatSession:
        with self._lock:
            if session_id not in self.sessions:
                raise SessionNotFound(session_id)
            session = self.sessions[session_id].model_copy(update={"status": status})
            self.sessions[session_id] = session
            return session

    def add_message(self, *, session_id, role, text, status, message_id=None, run_id=None) -> ChatMessage:
        now = utc_now()
        message = ChatMessage(message_id=message_id or new_message_id(), session_id=session_id, role=role,
                              text=text, status=status, run_id=run_id, created_at=now, updated_at=now)
        with self._lock:
            if session_id not in self.sessions:
                raise SessionNotFound(session_id)
            self.messages[message.message_id] = message
        return message

    def update_message(self, message_id, *, text=None, status=None, run_id=None) -> ChatMessage:
        changes = {key: value for key, value in (("text", text), ("status", status), ("run_id", run_id))
                   if value is not None}
        with self._lock:
            if message_id not in self.messages:
                raise MessageNotFound(message_id)
            message = self.messages[message_id].model_copy(update={**changes, "updated_at": utc_now()})
            self.messages[message_id] = message
            return message

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        with self._lock:
            return [message for message in self.messages.values() if message.session_id == session_id]


# --------------------------------------------------------------------------- #
# PostgreSQL (Supabase)
# --------------------------------------------------------------------------- #
class ChatSessionRow(SQLModel, table=True):
    __tablename__ = "chat_sessions"

    session_id: str = Field(primary_key=True)
    agent_id: str = Field(default=AGENT_ID)
    user_id: int = Field(index=True)
    client_id: str
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class ChatMessageRow(SQLModel, table=True):
    __tablename__ = "chat_messages"

    message_id: str = Field(primary_key=True)
    session_id: str = Field(foreign_key="chat_sessions.session_id", index=True)
    role: str
    text: str = Field(default="", sa_column=Column(Text, nullable=False))
    status: str
    run_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


def _session(row: ChatSessionRow) -> ChatSession:
    return ChatSession.model_validate(row.model_dump())


def _message(row: ChatMessageRow) -> ChatMessage:
    return ChatMessage.model_validate(row.model_dump())


class SqlChatStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_session(self, *, user_id: int, client_id: str) -> ChatSession:
        with Session(self.engine) as session:
            row = ChatSessionRow(session_id=new_session_id(), agent_id=AGENT_ID, user_id=user_id,
                                 client_id=client_id, status="active")
            session.add(row)
            session.commit()
            session.refresh(row)
            return _session(row)

    def get_session(self, session_id: str) -> ChatSession | None:
        with Session(self.engine) as session:
            row = session.get(ChatSessionRow, session_id)
            return _session(row) if row is not None else None

    def set_session_status(self, session_id: str, status: SessionStatus) -> ChatSession:
        with Session(self.engine) as session:
            row = session.get(ChatSessionRow, session_id)
            if row is None:
                raise SessionNotFound(session_id)
            row.status = status
            session.add(row)
            session.commit()
            session.refresh(row)
            return _session(row)

    def add_message(self, *, session_id, role, text, status, message_id=None, run_id=None) -> ChatMessage:
        with Session(self.engine) as session:
            if session.get(ChatSessionRow, session_id) is None:
                raise SessionNotFound(session_id)
            now = utc_now()
            row = ChatMessageRow(message_id=message_id or new_message_id(), session_id=session_id, role=role,
                                 text=text, status=status, run_id=run_id, created_at=now, updated_at=now)
            session.add(row)
            session.commit()
            session.refresh(row)
            return _message(row)

    def update_message(self, message_id, *, text=None, status=None, run_id=None) -> ChatMessage:
        with Session(self.engine) as session:
            row = session.get(ChatMessageRow, message_id)
            if row is None:
                raise MessageNotFound(message_id)
            for key, value in (("text", text), ("status", status), ("run_id", run_id)):
                if value is not None:
                    setattr(row, key, value)
            row.updated_at = utc_now()
            session.add(row)
            session.commit()
            session.refresh(row)
            return _message(row)

    def list_messages(self, session_id: str) -> list[ChatMessage]:
        with Session(self.engine) as session:
            rows = session.exec(
                select(ChatMessageRow)
                .where(ChatMessageRow.session_id == session_id)
                .order_by(ChatMessageRow.created_at, ChatMessageRow.message_id)
            ).all()
            return [_message(row) for row in rows]
