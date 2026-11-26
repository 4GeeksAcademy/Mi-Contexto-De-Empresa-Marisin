"""Stream SSE `GET /realtime/events` (`services/realtime/`, tiempo real · Parte 1).

Un stream infinito bloquearía el `TestClient`, así que los tests publican antes
de conectar y usan `StreamSettings(close_after_replay=True)`: el servidor envía
el replay y lo pendiente y cierra tras un intervalo de keep-alive sin eventos.
Cada test usa un broker nuevo (se sustituye el global del módulo, que es el que
leen tanto la dependencia como el listener del pipeline).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from data.pipelines.rfp_intake import config as rfp_config
from data.pipelines.rfp_intake import events as pipeline_events
from services.api.main import app
from services.api.security import create_access_token, get_current_user
from services.realtime import broker as broker_module
from services.realtime import router as realtime_router
from services.realtime.broker import EventBroker

BOOT = "1764150000"
EVENT_FIELDS = {
    "ticket_id", "rfp_id", "client_name", "client_country", "services_requested", "status", "created_at",
    "stage", "original_filename",
}


def ticket_payload(ticket_id: int = 42, **changes) -> dict:
    payload = {
        "ticket_id": ticket_id,
        "rfp_id": f"RFP-2026-{ticket_id:04d}",
        "client_name": "ModaViva",
        "client_country": "Spain",
        "services_requested": ["warehouse", "reverse"],
        "status": rfp_config.STATUS_ANALYZING,
        "created_at": "2026-11-26T10:15:00Z",
        "stage": rfp_config.STAGE_ORCHESTRATING,
        "original_filename": "trackflow-request-1.pdf",
    }
    return payload | changes


def parse_frames(text: str) -> list[dict]:
    """Frames SSE → dicts con `id`, `event`, `data` (líneas unidas), `retry` y `comments`."""
    frames = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        if not block.strip():
            continue
        frame: dict = {"comments": [], "data_lines": []}
        for line in block.split("\n"):
            if line.startswith(":"):
                frame["comments"].append(line[1:].strip())
                continue
            name, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if name == "data":
                frame["data_lines"].append(value)
            else:
                frame[name] = value
        frames.append(frame)
    return frames


def events_of(text: str, name: str) -> list[dict]:
    return [f for f in parse_frames(text) if f.get("event") == name]


@pytest.fixture
def broker(monkeypatch):
    fresh = EventBroker(boot_id=BOOT)
    monkeypatch.setattr(broker_module, "broker", fresh)
    return fresh


@pytest.fixture
def settings():
    return {"value": realtime_router.StreamSettings(keepalive_seconds=0.05, close_after_replay=True)}


@pytest.fixture
def client(broker, settings):
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_active": True, "role": "user"}
    app.dependency_overrides[realtime_router.get_stream_settings] = lambda: settings["value"]
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(realtime_router.get_stream_settings, None)


@pytest.fixture
def anonymous_client(broker, settings):
    app.dependency_overrides[realtime_router.get_stream_settings] = lambda: settings["value"]
    yield TestClient(app)
    app.dependency_overrides.pop(realtime_router.get_stream_settings, None)


# (a) autenticación ─────────────────────────────────────────────────────────
def test_without_token_the_stream_is_refused_with_401_before_opening(anonymous_client, broker):
    response = anonymous_client.get("/realtime/events")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert not response.headers["content-type"].startswith("text/event-stream")
    assert broker.subscriber_count == 0


def test_an_invalid_token_is_refused_with_401(anonymous_client):
    response = anonymous_client.get("/realtime/events", headers={"Authorization": "Bearer no-es-un-jwt"})

    assert response.status_code == 401


def test_the_backoffice_jwt_opens_the_stream(anonymous_client, monkeypatch):
    from services.api.services import users as user_service

    monkeypatch.setattr(user_service, "get_user_by_id", lambda user_id: {"id": user_id, "is_active": True})
    token = create_access_token(7)

    response = anonymous_client.get("/realtime/events", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


# (b) headers ───────────────────────────────────────────────────────────────
def test_with_jwt_the_response_is_an_uncached_event_stream(client):
    response = client.get("/realtime/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-cache" in response.headers["cache-control"]
    assert "no-transform" in response.headers["cache-control"]
    assert response.headers["x-accel-buffering"] == "no"


def test_a_new_connection_gets_retry_its_position_and_the_connected_comment(client, broker):
    broker.publish("rfp_ticket_created", ticket_payload(1))

    first = parse_frames(client.get("/realtime/events").text)[0]

    assert first["retry"] == "3000"
    assert first["id"] == f"{BOOT}-1"  # posición actual: sin replay de lo anterior
    assert first["comments"] == ["connected"]
    assert "event" not in first


# (c) wire del evento ───────────────────────────────────────────────────────
def test_rfp_ticket_created_is_a_named_event_with_a_flat_json_payload(client, broker):
    pipeline_events.emit(pipeline_events.EVENT_RFP_TICKET_CREATED, ticket_payload(42))

    response = client.get("/realtime/events", headers={"Last-Event-ID": f"{BOOT}-0"})

    assert "retry: 3000" in response.text
    [frame] = events_of(response.text, "rfp_ticket_created")
    assert frame["id"] == f"{BOOT}-1"
    assert len(frame["data_lines"]) == 1
    data = json.loads(frame["data_lines"][0])
    assert set(data) == EVENT_FIELDS
    assert not {"event", "data"} & set(data)
    assert data["status"] == "analizando"
    assert isinstance(data["ticket_id"], int) and data["ticket_id"] == 42
    assert data["client_country"] == "Spain"
    assert data["services_requested"] == ["warehouse", "reverse"]
    assert data["created_at"] == "2026-11-26T10:15:00Z"


def test_a_payload_with_unknown_fields_is_not_published(client, broker):
    pipeline_events.emit(pipeline_events.EVENT_RFP_TICKET_CREATED, ticket_payload(42, markdown="# documento"))

    assert client.get("/realtime/events", headers={"Last-Event-ID": f"{BOOT}-0"}).text.count("event:") == 0


# (d) replay por Last-Event-ID ──────────────────────────────────────────────
def test_last_event_id_of_this_boot_replays_only_later_events(client, broker):
    for ticket_id in (1, 2, 3):
        broker.publish("rfp_ticket_created", ticket_payload(ticket_id), dedupe_key=f"t:{ticket_id}")

    response = client.get("/realtime/events", headers={"Last-Event-ID": f"{BOOT}-1"})

    frames = events_of(response.text, "rfp_ticket_created")
    assert [f["id"] for f in frames] == [f"{BOOT}-2", f"{BOOT}-3"]
    assert [json.loads(f["data_lines"][0])["ticket_id"] for f in frames] == [2, 3]
    assert not events_of(response.text, "resync")


def test_last_event_id_at_the_latest_event_replays_nothing(client, broker):
    broker.publish("rfp_ticket_created", ticket_payload(1))

    response = client.get("/realtime/events", headers={"Last-Event-ID": f"{BOOT}-1"})

    assert "event:" not in response.text


# (e) resync ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("last_event_id", "reason"),
    [("1700000000-4", "server_restarted"), ("basura", "invalid_last_event_id"), (f"{BOOT}-99", "invalid_last_event_id")],
)
def test_an_id_the_server_cannot_resume_from_gets_a_resync(client, broker, last_event_id, reason):
    broker.publish("rfp_ticket_created", ticket_payload(1))

    response = client.get("/realtime/events", headers={"Last-Event-ID": last_event_id})

    [frame] = events_of(response.text, "resync")
    assert json.loads(frame["data_lines"][0]) == {"reason": reason}
    assert frame["id"] == f"{BOOT}-1"  # el cliente reanuda desde aquí tras el refetch
    assert not events_of(response.text, "rfp_ticket_created")


def test_an_id_that_left_the_buffer_gets_a_resync(client, monkeypatch):
    small = EventBroker(boot_id=BOOT, buffer_size=2)
    monkeypatch.setattr(broker_module, "broker", small)
    for ticket_id in (1, 2, 3, 4):
        small.publish("rfp_ticket_created", ticket_payload(ticket_id))

    response = client.get("/realtime/events", headers={"Last-Event-ID": f"{BOOT}-1"})

    [frame] = events_of(response.text, "resync")
    assert json.loads(frame["data_lines"][0]) == {"reason": "events_expired"}


# (f) dedupe en servidor ────────────────────────────────────────────────────
def test_the_same_ticket_id_is_only_notified_once(client, broker):
    pipeline_events.emit(pipeline_events.EVENT_RFP_TICKET_CREATED, ticket_payload(42))
    pipeline_events.emit(pipeline_events.EVENT_RFP_TICKET_CREATED, ticket_payload(42, stage="departamentos"))
    pipeline_events.emit(pipeline_events.EVENT_RFP_TICKET_CREATED, ticket_payload(43))

    response = client.get("/realtime/events", headers={"Last-Event-ID": f"{BOOT}-0"})

    frames = events_of(response.text, "rfp_ticket_created")
    assert [json.loads(f["data_lines"][0])["ticket_id"] for f in frames] == [42, 43]


# (g) keep-alive ────────────────────────────────────────────────────────────
def test_without_events_the_stream_sends_keep_alive_comments(client):
    text = client.get("/realtime/events").text

    assert ": keep-alive\n\n" in text
    assert "event:" not in text


def test_the_subscriber_is_released_when_the_stream_ends(client, broker):
    client.get("/realtime/events")

    assert broker.subscriber_count == 0


def test_an_event_published_from_another_thread_reaches_an_open_stream(client, broker, settings):
    import threading
    import time

    settings["value"] = realtime_router.StreamSettings(keepalive_seconds=0.5, close_after_replay=True)

    def publish_when_connected():  # como el pipeline, desde el threadpool de BackgroundTasks
        deadline = time.monotonic() + 5
        while broker.subscriber_count == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        pipeline_events.emit(pipeline_events.EVENT_RFP_TICKET_CREATED, ticket_payload(77))

    publisher = threading.Thread(target=publish_when_connected)
    publisher.start()
    text = client.get("/realtime/events").text
    publisher.join()

    [frame] = events_of(text, "rfp_ticket_created")
    assert json.loads(frame["data_lines"][0])["ticket_id"] == 77
