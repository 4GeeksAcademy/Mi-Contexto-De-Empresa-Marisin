import json
import logging
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from services.api.database import get_db
from services.api.main import app
from services.api.routes import telemetry as telemetry_route


MIXED_BATCH_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "telemetry" / "evidence" / "mixed-batch.json"
)


class FakeSession:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def fake_session():
    session = FakeSession()
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def inserted_batches(monkeypatch: pytest.MonkeyPatch, fake_session: FakeSession):
    batches: list[list[dict]] = []

    def fake_bulk_insert(session, rows):
        assert session is fake_session
        batches.append(rows)
        return len(rows)

    monkeypatch.setattr(telemetry_route, "bulk_insert_events", fake_bulk_insert)
    return batches


@pytest.fixture
def client(inserted_batches):
    test_client = TestClient(app)
    yield test_client
    test_client.close()


@pytest.fixture
def timing_log(caplog: pytest.LogCaptureFixture):
    logger = logging.getLogger("api.timing")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="api.timing")
    yield caplog
    logger.removeHandler(caplog.handler)


def valid_event(index: int = 1, event_type: str = "inbound_order_created", **properties) -> dict:
    default_properties = {
        "inbound_order_created": {
            "warehouse": "zaragoza",
            "client_id": "nova_beauty",
            "product_id": "TF-COS-001",
            "product_category": "cosmetics",
            "quantity": 12,
            "country": "ES",
            "order_id": 381,
        },
        "api_request_failed": {
            "api_endpoint": "/inventory/orders/outbound",
            "failure_reason": "http_5xx",
            "status_code": 503,
        },
        "page_viewed": {"route": "/inventory"},
    }[event_type]
    return {
        "eventId": str(UUID(int=index)),
        "timestamp": "2026-11-18T12:34:56.789Z",
        "sessionId": "550e8400-e29b-41d4-a716-446655440100",
        "userId": "usr_7b2c9f",
        "event_type": event_type,
        "schemaVersion": "1.0.0",
        "requestId": "550e8400-e29b-41d4-a716-446655440201",
        "properties": {**default_properties, **properties},
    }


def post_events(client: TestClient, events: list) -> dict:
    response = client.post("/telemetry/events", json={"events": events})
    assert response.status_code == 200
    return response.json()


def test_stores_business_and_technical_events_in_one_insert(client, inserted_batches):
    result = post_events(client, [valid_event(1), valid_event(2, "api_request_failed")])

    assert result == {"received": 2, "stored": 2, "rejected": 0}
    assert len(inserted_batches) == 1
    assert [row["event_type"] for row in inserted_batches[0]] == [
        "inbound_order_created",
        "api_request_failed",
    ]


def test_mixed_batch_stores_valid_events_and_counts_rejected(client, inserted_batches):
    batch = json.loads(MIXED_BATCH_PATH.read_text(encoding="utf-8"))

    response = client.post("/telemetry/events", json=batch)

    assert response.status_code == 200
    assert response.json() == {"received": 6, "stored": 2, "rejected": 4}
    assert len(inserted_batches) == 1
    assert len(inserted_batches[0]) == 2


def test_row_maps_columns_from_the_catalog(client, inserted_batches):
    post_events(client, [valid_event(1), valid_event(2, "api_request_failed")])
    inbound, failed = inserted_batches[0]

    assert inbound["service"] == "backoffice"
    assert inbound["level"] == "info"
    assert inbound["value"] == 12
    assert inbound["timestamp"].isoformat() == "2026-11-18T12:34:56.789000+00:00"
    assert inbound["message"].startswith("Inbound order created")
    assert failed["level"] == "error"
    assert failed["value"] == 503


def test_value_is_null_when_the_event_has_no_value_property(client, inserted_batches):
    post_events(client, [valid_event(1, "page_viewed")])

    assert inserted_batches[0][0]["value"] is None


def test_tags_keep_allowlisted_properties_and_envelope_ids(client, inserted_batches):
    post_events(client, [valid_event(1, unexpected_key="must_not_be_stored")])
    tags = inserted_batches[0][0]["tags"]

    assert tags["warehouse"] == "zaragoza"
    assert tags["client_id"] == "nova_beauty"
    assert tags["country"] == "ES"
    assert "unexpected_key" not in tags
    assert tags["eventId"] == str(UUID(int=1))
    assert tags["sessionId"] == "550e8400-e29b-41d4-a716-446655440100"
    assert tags["userId"] == "usr_7b2c9f"
    assert tags["schemaVersion"] == "1.0.0"
    assert tags["requestId"] == "550e8400-e29b-41d4-a716-446655440201"


def test_rejects_event_type_outside_the_catalog(client, inserted_batches):
    result = post_events(
        client, [valid_event(1), {**valid_event(2), "event_type": "inventory_teleported"}]
    )

    assert result == {"received": 2, "stored": 1, "rejected": 1}


def test_rejects_extra_envelope_field_without_cancelling_the_batch(client, inserted_batches):
    result = post_events(client, [valid_event(1), {**valid_event(2), "unexpected": "value"}])

    assert result == {"received": 2, "stored": 1, "rejected": 1}


def test_empty_batch_does_not_touch_the_database(client, inserted_batches):
    assert post_events(client, []) == {"received": 0, "stored": 0, "rejected": 0}
    assert inserted_batches == []


def test_all_invalid_batch_does_not_touch_the_database(client, inserted_batches):
    event = valid_event()
    del event["eventId"]

    assert post_events(client, [event, "no-soy-un-objeto"]) == {
        "received": 2,
        "stored": 0,
        "rejected": 2,
    }
    assert inserted_batches == []


def test_rejects_batch_over_fifty_events(client, inserted_batches):
    response = client.post(
        "/telemetry/events",
        json={"events": [valid_event(index) for index in range(1, 52)]},
    )

    assert response.status_code == 422
    assert inserted_batches == []


@pytest.mark.parametrize("body", [{}, {"events": "not-a-list"}, []])
def test_rejects_unparseable_envelope(client, body):
    response = client.post("/telemetry/events", json=body)

    assert response.status_code == 422


def test_database_failure_returns_503_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch, fake_session: FakeSession
):
    def failing_bulk_insert(session, rows):
        raise SQLAlchemyError("connection lost")

    monkeypatch.setattr(telemetry_route, "bulk_insert_events", failing_bulk_insert)
    # Sin "with": el arranque (create_all y semilla) no debe ejecutarse en los tests.
    test_client = TestClient(app)
    response = test_client.post("/telemetry/events", json={"events": [valid_event()]})
    test_client.close()

    assert response.status_code == 503
    assert fake_session.rollbacks == 1


def test_logs_counts_and_types_but_never_event_data(client, timing_log):
    event = valid_event(1, unexpected_key="TELEMETRY_PROPERTY_MUST_NOT_BE_LOGGED")
    invalid = {**valid_event(2), "timestamp": "2026-11-18T12:34:56"}
    invalid["properties"]["client_id"] = "TELEMETRY_PROPERTY_MUST_NOT_BE_LOGGED"

    post_events(client, [event, invalid])

    assert "received=2 stored=1 rejected=1" in timing_log.text
    assert "inbound_order_created" in timing_log.text
    assert "timezone_aware" in timing_log.text
    assert "TELEMETRY_PROPERTY_MUST_NOT_BE_LOGGED" not in timing_log.text
    assert "nova_beauty" not in timing_log.text
    assert "usr_7b2c9f" not in timing_log.text
