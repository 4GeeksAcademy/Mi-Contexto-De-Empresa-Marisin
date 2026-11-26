"""Contrato del WebSocket del chat del First-line CX agent (sin LLM, sin PostgreSQL, deterministas).

`get_chat_store()`, `get_turn_runner()` y `get_turn_manager()` se sustituyen por
un `InMemoryChatStore`, un runner falso y un `ChatTurnManager` nuevo en cada test.
El runner falso emite tokens con pausas, respeta `cancel_event` como el agente
real (`AgentRunCancelled`) y registra cada llamada; con `hold_after` se detiene
tras N tokens hasta que lo interrumpan o lo suelten, así que el orden de los
eventos es determinista.

Todas las conexiones de un test comparten **un** event loop (un `BlockingPortal`
asignado al `TestClient`), como en uvicorn: el turno sobrevive a que su conexión
se cierre. No se usa `with TestClient(app)` para no ejecutar el `startup` de la
API (`create_all` contra Supabase y `seed_database()`).

    python -m pytest tests/test_agent_chat_ws.py
"""

import json
import threading
import time
from pathlib import Path

import anyio
import pytest
from anyio.from_thread import start_blocking_portal
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from services.agent import runner
from services.agent.chat import router as chat_router
from services.agent.chat import turns
from services.agent.chat.store import InMemoryChatStore
from services.api.main import app
from services.api.security import create_access_token
from services.api.services import users as user_service

OWNER, STRANGER, MANAGER = 1, 2, 3
USERS = {
    OWNER: {"id": OWNER, "is_active": True, "role": "user"},
    STRANGER: {"id": STRANGER, "is_active": True, "role": "user"},
    MANAGER: {"id": MANAGER, "is_active": True, "role": "manager"},
}
QUESTION = "¿Dónde está mi pedido?"
NEW_INPUT = "espera, quiero hacer una devolución, no rastrear el pedido"
TIMEOUT = 5


class FakeRunner:
    """Doble de `run_agent(question, conversation_id=…, user=…, on_token=…, cancel_event=…)`."""

    def __init__(self, hold_after: int | None = None):
        self.hold_after = hold_after  # solo en la primera llamada
        self.release = threading.Event()
        self.calls: list[dict] = []
        self.cancel_seen: list[int] = []

    @staticmethod
    def tokens_for(question: str) -> list[str]:
        return [f"Sobre «{question}»", ": ", "esto ", "es ", "lo ", "que ", "sé."]

    def __call__(self, question, *, conversation_id, user, on_token, cancel_event):
        index = len(self.calls)
        self.calls.append({"question": question, "conversation_id": conversation_id, "user_id": user["id"]})
        hold = self.hold_after if index == 0 else None
        for position, token in enumerate(self.tokens_for(question)):
            if position == hold:
                deadline = time.monotonic() + TIMEOUT
                while not (cancel_event.is_set() or self.release.is_set()) and time.monotonic() < deadline:
                    time.sleep(0.005)
            if cancel_event.is_set():  # como `run_agent`: sin más tokens y `AgentRunCancelled`
                self.cancel_seen.append(index)
                raise runner.AgentRunCancelled(f"run-{index}", tokens_sent=position, stream_closed=True)
            on_token(token)
            time.sleep(0.002)
        return runner.AgentResult(
            run_id=f"run-{index}", status="answered", answer="".join(self.tokens_for(question)),
            trace_path=Path("unused.json"), sources=("rag",), conversation_id=conversation_id,
        )


@pytest.fixture
def users(monkeypatch):
    monkeypatch.setattr(user_service, "get_user_by_id", lambda user_id: USERS.get(user_id))
    return {user_id: create_access_token(user_id) for user_id in USERS}


@pytest.fixture
def store():
    return InMemoryChatStore()


@pytest.fixture
def manager():
    return turns.ChatTurnManager(interrupt_wait_seconds=TIMEOUT)


@pytest.fixture
def fake_runner():
    return FakeRunner()


@pytest.fixture
def client(store, manager, fake_runner, users):
    app.dependency_overrides[chat_router.get_chat_store] = lambda: store
    app.dependency_overrides[turns.get_turn_runner] = lambda: fake_runner
    app.dependency_overrides[turns.get_turn_manager] = lambda: manager
    with start_blocking_portal(backend="asyncio") as portal:
        test_client = TestClient(app)
        test_client.portal = portal  # un solo event loop para todas las conexiones, sin `startup`
        yield test_client
        fake_runner.release.set()
    for dependency in (chat_router.get_chat_store, turns.get_turn_runner, turns.get_turn_manager):
        app.dependency_overrides.pop(dependency, None)


@pytest.fixture
def session(store):
    return store.create_session(user_id=OWNER, client_id="ecowear_usa")


def ws_url(session_id, token=None):
    url = f"/agent/chat/sessions/{session_id}/ws"
    return f"{url}?token={token}" if token is not None else url


def receive(ws, timeout=TIMEOUT):
    """`receive_json` con tiempo máximo: un fallo nunca deja el test colgado."""

    async def next_message():
        with anyio.fail_after(timeout):
            return await ws._send_rx.receive()

    message = ws.portal.call(next_message)
    if message["type"] == "websocket.close":
        raise WebSocketDisconnect(message.get("code", 1000), message.get("reason"))
    return json.loads(message["text"])


def receive_until(ws, predicate):
    events = []
    while True:
        event = receive(ws)
        events.append(event)
        if predicate(event):
            return events


def is_event(name, **fields):
    return lambda event: event["event"] == name and all(event["data"].get(k) == v for k, v in fields.items())


def send(ws, event, **data):
    ws.send_json({"event": event, "data": data})


def close_code_without_frames(client, url):
    with client.websocket_connect(url) as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            receive(ws)  # lo primero que llega es el cierre: ningún evento antes
    return closed.value.code


def tokens_of(events, message_id):
    return [event["data"] for event in events if event["event"] == "token_chunk"
            and event["data"]["message_id"] == message_id]


# (a) auth ──────────────────────────────────────────────────────────────────
def test_without_token_the_socket_closes_with_4401_before_any_event(client, session):
    assert close_code_without_frames(client, ws_url(session.session_id)) == 4401


def test_an_invalid_token_closes_with_4401_before_any_event(client, session):
    assert close_code_without_frames(client, ws_url(session.session_id, "no-es-un-jwt")) == 4401


# (b) sesión y permisos ─────────────────────────────────────────────────────
def test_an_unknown_session_closes_with_4404(client, users):
    assert close_code_without_frames(client, ws_url("chat_000000000000", users[OWNER])) == 4404


def test_another_user_closes_with_4403_but_a_manager_can_join(client, session, users):
    assert close_code_without_frames(client, ws_url(session.session_id, users[STRANGER])) == 4403

    with client.websocket_connect(ws_url(session.session_id, users[MANAGER])) as ws:
        assert receive(ws)["event"] == "session_snapshot"


# (c) primer frame ──────────────────────────────────────────────────────────
def test_the_first_frame_is_the_session_snapshot(client, session, users):
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as ws:
        snapshot = receive(ws)

    assert snapshot["event"] == "session_snapshot"
    data = snapshot["data"]
    assert data["session_id"] == session.session_id
    assert data["session"] == {
        "session_id": session.session_id, "agent_id": "first_line_cx", "user_id": OWNER,
        "client_id": "ecowear_usa", "status": "active", "created_at": data["session"]["created_at"],
    }
    assert data["messages"] == []
    assert data["active_generation"] is None


# (d) un turno completo ─────────────────────────────────────────────────────
def test_a_user_message_streams_numbered_tokens_and_completes(client, session, users, store, fake_runner):
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as ws:
        receive(ws)
        send(ws, "user_message", session_id=session.session_id, text=f"  {QUESTION}  ")
        events = receive_until(ws, is_event("generation_completed"))

    names = [event["event"] for event in events]
    assert names[:2] == ["user_message", "generation_started"]
    assert names[-1] == "generation_completed"
    echo, started, completed = events[0]["data"], events[1]["data"], events[-1]["data"]
    assert echo["text"] == QUESTION and echo["message_id"].startswith("msg_") and echo["created_at"]
    message_id = started["message_id"]
    assert message_id.startswith("msg_") and message_id != echo["message_id"]
    chunks = tokens_of(events, message_id)
    assert [chunk["sequence"] for chunk in chunks] == list(range(1, len(FakeRunner.tokens_for(QUESTION)) + 1))
    assert all(chunk["session_id"] == session.session_id for chunk in chunks)
    assert "".join(chunk["token"] for chunk in chunks) == completed["answer"]
    assert completed == {"session_id": session.session_id, "message_id": message_id,
                         "answer": "".join(FakeRunner.tokens_for(QUESTION)), "status": "answered", "sources": ["rag"]}

    messages = store.list_messages(session.session_id)
    assert [(m.role, m.status) for m in messages] == [("user", "completed"), ("assistant", "completed")]
    assert messages[1].message_id == message_id and messages[1].text == completed["answer"]
    assert messages[1].run_id == "run-0"
    assert fake_runner.calls == [{"question": QUESTION, "conversation_id": session.session_id, "user_id": OWNER}]


def test_a_route_without_llm_sends_the_answer_as_a_single_token_chunk(client, session, users):
    def template_runner(question, *, conversation_id, user, on_token, cancel_event):
        return runner.AgentResult(run_id="run-t", status="tool_fallback", answer="Plantilla de la tool.",
                                  trace_path=Path("unused.json"), sources=("incidents",))

    app.dependency_overrides[turns.get_turn_runner] = lambda: template_runner
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as ws:
        receive(ws)
        send(ws, "user_message", session_id=session.session_id, text="estado del ticket 3")
        events = receive_until(ws, is_event("generation_completed"))

    chunks = [event["data"] for event in events if event["event"] == "token_chunk"]
    assert [(chunk["token"], chunk["sequence"]) for chunk in chunks] == [("Plantilla de la tool.", 1)]
    assert events[-1]["data"]["status"] == "tool_fallback"


# (e) interrupción ──────────────────────────────────────────────────────────
def test_interrupting_aborts_the_generation_keeps_the_partial_and_starts_a_new_turn(
    client, session, users, store, manager, fake_runner
):
    fake_runner.hold_after = 2
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as ws:
        receive(ws)
        send(ws, "user_message", session_id=session.session_id, text=QUESTION)
        before = receive_until(ws, lambda event: event["event"] == "token_chunk" and event["data"]["sequence"] == 2)
        old_id = before[1]["data"]["message_id"]
        send(ws, "interrupt_requested", session_id=session.session_id, new_input=NEW_INPUT)
        after = receive_until(ws, lambda event: event["event"] == "generation_completed")

    # Métrica del abort: cero token_chunk del message_id viejo después de generation_interrupted.
    interrupted_at = next(i for i, event in enumerate(after) if event["event"] == "generation_interrupted")
    assert after[interrupted_at]["data"] == {"session_id": session.session_id, "message_id": old_id,
                                             "status": "interrupted"}
    assert tokens_of(after[interrupted_at:], old_id) == []
    partial = "".join(chunk["token"] for chunk in tokens_of(before + after, old_id))
    assert partial == "".join(FakeRunner.tokens_for(QUESTION)[:2])

    # Turno nuevo: eco de new_input, otro message_id y una respuesta que refleja new_input.
    rest = after[interrupted_at + 1:]
    assert rest[0]["event"] == "user_message" and rest[0]["data"]["text"] == NEW_INPUT
    assert rest[1]["event"] == "generation_started"
    new_id = rest[1]["data"]["message_id"]
    assert new_id != old_id
    assert [chunk["sequence"] for chunk in tokens_of(rest, new_id)][0] == 1
    assert NEW_INPUT in rest[-1]["data"]["answer"] and rest[-1]["data"]["message_id"] == new_id

    # El parcial se conserva como `interrupted` (con exactamente lo emitido) y nunca se sobrescribe.
    messages = store.list_messages(session.session_id)
    assert [(m.role, m.status) for m in messages] == [
        ("user", "completed"), ("assistant", "interrupted"), ("user", "completed"), ("assistant", "completed"),
    ]
    assert (messages[1].message_id, messages[1].text, messages[1].run_id) == (old_id, partial, "run-0")
    assert messages[2].text == NEW_INPUT
    assert store.get_session(session.session_id).status == "active"

    # El agente vio la cancelación y la segunda corrida recibió new_input.
    assert fake_runner.cancel_seen == [0]
    assert [call["question"] for call in fake_runner.calls] == [QUESTION, NEW_INPUT]
    assert manager.counters["dropped_after_abort"] == 0  # determinista solo con este runner falso
    assert manager.counters["turns_interrupted"] == 1


def test_interrupting_without_new_input_leaves_the_session_interrupted(client, session, users, store, fake_runner):
    fake_runner.hold_after = 1
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as ws:
        receive(ws)
        send(ws, "user_message", session_id=session.session_id, text=QUESTION)
        receive_until(ws, is_event("token_chunk", sequence=1))
        send(ws, "interrupt_requested", session_id=session.session_id)
        interrupted = receive_until(ws, is_event("generation_interrupted"))[-1]

    assert interrupted["data"]["status"] == "interrupted"
    assert store.get_session(session.session_id).status == "interrupted"
    assert len(fake_runner.calls) == 1


# (f) errores del contrato ──────────────────────────────────────────────────
def test_a_user_message_during_a_generation_is_refused_with_generation_in_progress(client, session, users, fake_runner):
    fake_runner.hold_after = 1
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as ws:
        receive(ws)
        send(ws, "user_message", session_id=session.session_id, text=QUESTION)
        started = receive_until(ws, is_event("generation_started"))[-1]
        send(ws, "user_message", session_id=session.session_id, text="otra pregunta")
        error = receive_until(ws, is_event("chat_error"))[-1]
        fake_runner.release.set()
        receive_until(ws, is_event("generation_completed"))

    assert error["data"]["code"] == "generation_in_progress"
    assert error["data"]["message_id"] == started["data"]["message_id"]
    assert len(fake_runner.calls) == 1


def test_interrupting_with_nothing_in_progress_returns_nothing_to_interrupt(client, session, users):
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as ws:
        receive(ws)
        send(ws, "interrupt_requested", session_id=session.session_id, new_input=NEW_INPUT)
        error = receive(ws)

    assert error["event"] == "chat_error"
    assert error["data"]["code"] == "nothing_to_interrupt"


@pytest.mark.parametrize("frame", [
    {"event": "user_message", "data": {"text": "   "}},
    {"event": "user_message", "data": {"text": "x" * 501}},
    {"event": "user_message", "data": {"session_id": "chat_otraotraotr", "text": "hola"}},
    {"event": "unknown_event", "data": {}},
    "esto no es JSON",
])
def test_invalid_frames_return_invalid_message(client, session, users, fake_runner, frame):
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as ws:
        receive(ws)
        if isinstance(frame, str):
            ws.send_text(frame)
        else:
            frame["data"].setdefault("session_id", session.session_id)
            ws.send_json(frame)
        error = receive(ws)

    assert error["event"] == "chat_error"
    assert error["data"]["code"] == "invalid_message"
    assert error["data"]["session_id"] == session.session_id
    assert fake_runner.calls == []


# (g) reconexión ────────────────────────────────────────────────────────────
def test_reconnecting_rehydrates_the_history_including_the_interrupted_message(client, session, users, fake_runner):
    fake_runner.hold_after = 2
    url = ws_url(session.session_id, users[OWNER])
    with client.websocket_connect(url) as ws:
        receive(ws)
        send(ws, "user_message", session_id=session.session_id, text=QUESTION)
        old_id = receive_until(ws, is_event("token_chunk", sequence=2))[-1]["data"]["message_id"]
        send(ws, "interrupt_requested", session_id=session.session_id)
        receive_until(ws, is_event("generation_interrupted"))

    with client.websocket_connect(url) as ws:
        snapshot = receive(ws)

    assert snapshot["event"] == "session_snapshot"
    messages = snapshot["data"]["messages"]
    assert [(m["role"], m["status"]) for m in messages] == [("user", "completed"), ("assistant", "interrupted")]
    assert messages[1]["message_id"] == old_id
    assert messages[1]["text"] == "".join(FakeRunner.tokens_for(QUESTION)[:2])
    assert snapshot["data"]["session"]["status"] == "interrupted"
    assert snapshot["data"]["active_generation"] is None


def test_reconnecting_mid_turn_resumes_from_the_partial_text_without_gaps_or_duplicates(
    client, session, users, fake_runner, store
):
    fake_runner.hold_after = 2
    url = ws_url(session.session_id, users[OWNER])
    with client.websocket_connect(url) as ws:
        receive(ws)
        send(ws, "user_message", session_id=session.session_id, text=QUESTION)
        message_id = receive_until(ws, is_event("token_chunk", sequence=2))[-1]["data"]["message_id"]
    # El socket se cerró (corte de red); el turno sigue en el servidor.

    with client.websocket_connect(url) as ws:
        snapshot = receive(ws)
        fake_runner.release.set()
        events = receive_until(ws, is_event("generation_completed"))

    active = snapshot["data"]["active_generation"]
    tokens = FakeRunner.tokens_for(QUESTION)
    assert active == {"message_id": message_id, "text": "".join(tokens[:2]), "sequence": 2}
    assert [(m["role"], m["status"]) for m in snapshot["data"]["messages"]] == [
        ("user", "completed"), ("assistant", "streaming"),
    ]
    chunks = tokens_of(events, message_id)
    assert [chunk["sequence"] for chunk in chunks] == list(range(3, len(tokens) + 1))
    assert active["text"] + "".join(chunk["token"] for chunk in chunks) == events[-1]["data"]["answer"]
    assert len(fake_runner.calls) == 1
    assert store.list_messages(session.session_id)[1].status == "completed"


# (h) supervisor ────────────────────────────────────────────────────────────
def test_owner_and_supervisor_receive_the_same_events_and_the_agent_runs_once(client, session, users, fake_runner):
    with client.websocket_connect(ws_url(session.session_id, users[OWNER])) as owner, \
            client.websocket_connect(ws_url(session.session_id, users[MANAGER])) as supervisor:
        receive(owner), receive(supervisor)
        send(owner, "user_message", session_id=session.session_id, text=QUESTION)
        owner_events = receive_until(owner, is_event("generation_completed"))
        supervisor_events = receive_until(supervisor, is_event("generation_completed"))

        send(supervisor, "user_message", session_id=session.session_id, text="soy el supervisor")
        refused = receive(supervisor)

    assert supervisor_events == owner_events
    assert len(fake_runner.calls) == 1
    assert refused["event"] == "chat_error" and refused["data"]["code"] == "forbidden"
    assert len(fake_runner.calls) == 1


# (i) creación de la sesión ─────────────────────────────────────────────────
def test_post_sessions_creates_a_chat_session_with_the_briefing_fields(client, users, store):
    response = client.post("/agent/chat/sessions", json={"client_id": "ecowear_usa"},
                           headers={"Authorization": f"Bearer {users[OWNER]}"})

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"session_id", "agent_id", "user_id", "client_id", "status", "created_at"}
    assert body["session_id"].startswith("chat_") and len(body["session_id"]) == 17
    assert (body["agent_id"], body["user_id"], body["client_id"], body["status"]) == (
        "first_line_cx", OWNER, "ecowear_usa", "active",
    )
    assert store.get_session(body["session_id"]) is not None


def test_post_sessions_without_token_is_401(client):
    response = client.post("/agent/chat/sessions", json={"client_id": "ecowear_usa"})

    assert response.status_code == 401


def test_post_sessions_rejects_an_invalid_client_id(client, users):
    response = client.post("/agent/chat/sessions", json={"client_id": "no válido!"},
                           headers={"Authorization": f"Bearer {users[OWNER]}"})

    assert response.status_code == 422


def test_without_postgresql_post_is_503_and_the_socket_closes_with_1011(client, session, users):
    app.dependency_overrides[chat_router.get_chat_store] = lambda: None

    response = client.post("/agent/chat/sessions", json={"client_id": "ecowear_usa"},
                           headers={"Authorization": f"Bearer {users[OWNER]}"})

    assert response.status_code == 503
    assert close_code_without_frames(client, ws_url(session.session_id, users[OWNER])) == 1011
