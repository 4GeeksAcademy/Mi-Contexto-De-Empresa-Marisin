from datetime import datetime, timezone

from sqlalchemy.dialects import postgresql
from sqlmodel import SQLModel

from services.api.telemetry_storage import (
    build_bulk_insert,
    bulk_insert_events,
    telemetry_events,
)


def make_row(index: int) -> dict:
    return {
        "timestamp": datetime(2026, 11, 19, 10, 0, index, tzinfo=timezone.utc),
        "service": "backoffice",
        "event_type": "page_viewed",
        "level": "info",
        "value": None,
        "message": "Backoffice route view, using a route template without query parameters.",
        "tags": {"eventId": f"event-{index}"},
    }


class FakeConnection:
    def __init__(self):
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)


class FakeSession:
    def __init__(self):
        self.fake_connection = FakeConnection()
        self.commits = 0

    def connection(self):
        return self.fake_connection

    def commit(self):
        self.commits += 1


def test_table_has_the_eight_columns_of_the_contract():
    assert [column.name for column in telemetry_events.columns] == [
        "id",
        "timestamp",
        "service",
        "event_type",
        "level",
        "value",
        "message",
        "tags",
    ]


def test_table_is_not_created_by_sqlmodel_create_all():
    assert "telemetry_events" not in SQLModel.metadata.tables
    assert "public.telemetry_events" not in SQLModel.metadata.tables


def test_batch_compiles_to_a_single_multi_row_insert():
    statement = build_bulk_insert([make_row(1), make_row(2), make_row(3)])
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert sql.count("INSERT INTO") == 1
    assert "public.telemetry_events" in sql
    assert sql.count("VALUES") == 1
    assert sql.count("%(event_type_m") == 3


def test_bulk_insert_executes_once_and_commits_once():
    session = FakeSession()

    stored = bulk_insert_events(session, [make_row(1), make_row(2), make_row(3)])

    assert stored == 3
    assert len(session.fake_connection.statements) == 1
    assert session.commits == 1


def test_empty_batch_does_not_touch_the_database():
    session = FakeSession()

    assert bulk_insert_events(session, []) == 0
    assert session.fake_connection.statements == []
    assert session.commits == 0
