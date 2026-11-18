import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from services.api.main import app


@pytest.fixture
def client():
    test_client = TestClient(app)
    yield test_client
    test_client.close()


def valid_event(index: int = 1) -> dict:
    return {
        "eventId": str(UUID(int=index)),
        "timestamp": "2026-11-18T12:34:56.789Z",
        "sessionId": "550e8400-e29b-41d4-a716-446655440100",
        "userId": "usr_7b2c9f",
        "event_type": "inbound_order_created",
        "schemaVersion": "1.0.0",
        "requestId": "550e8400-e29b-41d4-a716-446655440201",
        "properties": {"test_value": "TELEMETRY_PROPERTY_MUST_NOT_BE_LOGGED"},
    }


def test_accepts_two_events_without_authorization_and_logs_only_event_types(
    client: TestClient, caplog: pytest.LogCaptureFixture
):
    logger = logging.getLogger("api.timing")
    logger.addHandler(caplog.handler)
    try:
        response = client.post(
            "/telemetry/events",
            json={
                "events": [
                    valid_event(1),
                    {**valid_event(2), "event_type": "outbound_order_created"},
                ]
            },
        )
    finally:
        logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    assert response.json() == {"received": 2}
    assert "inbound_order_created" in caplog.text
    assert "outbound_order_created" in caplog.text
    assert "TELEMETRY_PROPERTY_MUST_NOT_BE_LOGGED" not in caplog.text


def test_accepts_empty_batch(client: TestClient):
    response = client.post("/telemetry/events", json={"events": []})

    assert response.status_code == 200
    assert response.json() == {"received": 0}


def test_rejects_event_without_event_id(client: TestClient):
    event = valid_event()
    del event["eventId"]

    response = client.post("/telemetry/events", json={"events": [event]})

    assert response.status_code == 422


def test_rejects_extra_envelope_property(client: TestClient):
    event = {**valid_event(), "unexpected": "value"}

    response = client.post("/telemetry/events", json={"events": [event]})

    assert response.status_code == 422


def test_rejects_batch_over_fifty_events(client: TestClient):
    response = client.post(
        "/telemetry/events",
        json={"events": [valid_event(index) for index in range(1, 52)]},
    )

    assert response.status_code == 422
