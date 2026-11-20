"""Dead Letter Queue persistida: `public.task_dead_letters`.

La tabla se crea con `services/sql/002_task_dead_letters.sql`. Cuando una tarea
agota sus reintentos, `services/tasks.py` publica un mensaje en la cola
`dead_letter`; la tarea `trackflow.dead_letter.record` lo consume y llama a
`record()`, que deja una fila con el `task_id`, el número de intento, el error y
el timestamp del fallo.

La inserción es idempotente por `task_id` (índice único): si el mensaje de la DLQ
se reentrega, no se duplica la fila. Como `job_runner.py`, este módulo no importa
FastAPI y se prueba con un SQLite en memoria.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    Table,
    Text,
    Uuid,
    insert,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError


ERROR_MESSAGE_MAX_LENGTH = 4000

dead_letters_metadata = MetaData()

task_dead_letters = Table(
    "task_dead_letters",
    dead_letters_metadata,
    Column("id", Uuid, primary_key=True, default=uuid4),
    Column("task_id", Text, nullable=False, unique=True),
    Column("task_name", Text, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("max_retries", Integer, nullable=False),
    Column("error_type", Text, nullable=False),
    Column("error_message", Text, nullable=False),
    Column("task_kwargs", JSON, nullable=False, default=dict),
    Column("failed_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
)


@dataclass(frozen=True)
class DeadLetter:
    task_id: str
    task_name: str
    attempt: int
    max_retries: int
    error_type: str
    error_message: str
    task_kwargs: dict[str, Any]
    failed_at: datetime


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_payload(
    *,
    task_id: str,
    task_name: str,
    attempt: int,
    max_retries: int,
    exc: BaseException,
    task_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Mensaje ligero para la cola `dead_letter` (serializable a JSON)."""
    return {
        "task_id": task_id,
        "task_name": task_name,
        "attempt": attempt,
        "max_retries": max_retries,
        "error_type": type(exc).__name__,
        "error_message": str(exc)[:ERROR_MESSAGE_MAX_LENGTH],
        "task_kwargs": task_kwargs,
        "failed_at": utc_now().isoformat(),
    }


def from_payload(payload: dict[str, Any]) -> DeadLetter:
    failed_at = datetime.fromisoformat(payload["failed_at"])
    if failed_at.tzinfo is None:
        failed_at = failed_at.replace(tzinfo=timezone.utc)
    return DeadLetter(
        task_id=str(payload["task_id"]),
        task_name=str(payload["task_name"]),
        attempt=int(payload["attempt"]),
        max_retries=int(payload["max_retries"]),
        error_type=str(payload["error_type"]),
        error_message=str(payload["error_message"])[:ERROR_MESSAGE_MAX_LENGTH],
        task_kwargs=dict(payload.get("task_kwargs") or {}),
        failed_at=failed_at,
    )


def record(engine: Engine, letter: DeadLetter) -> bool:
    """Inserta la fila de la DLQ. Devuelve `False` si ese `task_id` ya estaba registrado."""
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(task_dead_letters).values(
                    id=uuid4(),
                    task_id=letter.task_id,
                    task_name=letter.task_name,
                    attempt=letter.attempt,
                    max_retries=letter.max_retries,
                    error_type=letter.error_type,
                    error_message=letter.error_message,
                    task_kwargs=letter.task_kwargs,
                    failed_at=letter.failed_at,
                    recorded_at=utc_now(),
                )
            )
    except IntegrityError:
        return False
    return True


def get(engine: Engine, task_id: str) -> dict[str, Any] | None:
    with engine.connect() as connection:
        row = connection.execute(
            select(task_dead_letters).where(task_dead_letters.c.task_id == task_id)
        ).mappings().first()
    return dict(row) if row is not None else None
