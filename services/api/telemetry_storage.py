"""Acceso de escritura a la tabla de telemetría de Supabase (D32 y D38).

La tabla se crea con `services/api/sql/001_telemetry_events.sql`. Aquí solo se
declara para poder insertar: vive en un `MetaData` propio, fuera de
`SQLModel.metadata`, para que `create_all()` del arranque nunca la cree sin sus
índices, triggers ni RLS.

La tabla es de solo escritura: este módulo no ofrece actualizaciones ni borrados.
"""

from typing import Any

from sqlalchemy import Column, DateTime, MetaData, Numeric, Table, Text, insert, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlmodel import Session


telemetry_metadata = MetaData()

telemetry_events = Table(
    "telemetry_events",
    telemetry_metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("service", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("level", Text, nullable=False, server_default=text("'info'")),
    Column("value", Numeric, nullable=True),
    Column("message", Text, nullable=True),
    Column("tags", JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    schema="public",
)


def build_bulk_insert(rows: list[dict[str, Any]]):
    """Una única sentencia `INSERT ... VALUES (...), (...)` para todo el lote."""
    return insert(telemetry_events).values(rows)


def bulk_insert_events(session: Session, rows: list[dict[str, Any]]) -> int:
    """Inserta las filas de un lote en una sola sentencia y una sola transacción."""
    if not rows:
        return 0
    # La conexión de la sesión comparte su transacción: el commit la cierra entera.
    session.connection().execute(build_bulk_insert(rows))
    session.commit()
    return len(rows)
