"""NIST · Protect: límite de llamadas a los endpoints que invocan un modelo (criterio de la rúbrica).

* Ventanas deslizantes por usuario (minuto y día) y global, con reloj falso.
* `POST /agent/query`: la petición N+1 recibe **429** con `Retry-After` y el grafo
  **no** se ejecuta (ninguna llamada al LLM); el presupuesto se recupera al pasar la ventana.
* El presupuesto es por usuario: otro usuario sigue pudiendo preguntar.
* `POST /knowledge/query` y el chat por WebSocket gastan el mismo presupuesto.
* Cada rechazo deja un evento de guardrail `rate_limit` (tipo `security`).

    python -m pytest tests/test_nist_rate_limit.py
"""

import pytest
from fastapi.testclient import TestClient

from data.pipelines import rag as rag_pipeline
from services.agent import runner
from services.agent.chat import router as chat_router
from services.agent.chat.schemas import EVENT_CHAT_ERROR, ChatErrorData
from services.agent.harness import usage_limits
from services.api.main import app
from services.api.security import get_current_user

CUSTOMER = {"id": 9001, "is_active": True, "role": "user"}
OTHER_CUSTOMER = {"id": 9002, "is_active": True, "role": "user"}
STAFF = {"id": 42, "is_active": True, "role": "manager"}
QUESTION = "¿Cuál es el plazo de devolución en España?"


class FakeClock:
    def __init__(self):
        self.now = 1_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    clock = FakeClock()
    usage_limits.reset_limiter(usage_limits.LlmUsageLimiter(3, 5, 100, clock=clock))
    return clock


@pytest.fixture
def agent_runs(monkeypatch):
    runs = []

    def fake_run_agent(question, **kwargs):
        runs.append(question)
        return runner.AgentResult(run_id="00000000-0000-0000-0000-000000000001", status="answered",
                                  answer="Respuesta de prueba.", trace_path=None, conversation_id="c1")

    monkeypatch.setattr(runner, "run_agent", fake_run_agent)
    return runs


@pytest.fixture
def as_user():
    def _as(user):
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield _as
    app.dependency_overrides.pop(get_current_user, None)


# --------------------------------------------------------------------------- #
# Limitador
# --------------------------------------------------------------------------- #
def test_limiter_windows_per_user_per_day_and_global():
    clock = FakeClock()
    limiter = usage_limits.LlmUsageLimiter(per_minute=2, per_day=3, global_per_minute=4, clock=clock)

    assert [limiter.check("u1").allowed for _ in range(3)] == [True, True, False]
    blocked = limiter.check("u1")
    assert blocked.scope == "user_minute" and 1 <= blocked.retry_after <= 60

    clock.now += 61
    assert limiter.check("u1").allowed  # tercera del día
    assert limiter.check("u1").scope == "user_day"  # cuarta: agotado el día

    assert limiter.check("u2").allowed and limiter.check("u2").allowed
    assert limiter.check("u3").allowed  # 4 aceptadas en el último minuto entre todos
    assert limiter.check("u4").scope == "global_minute"  # cortacircuitos de coste


def test_a_rejected_request_does_not_consume_budget():
    clock = FakeClock()
    limiter = usage_limits.LlmUsageLimiter(per_minute=1, per_day=2, global_per_minute=10, clock=clock)
    assert limiter.check("u1").allowed
    for _ in range(5):
        assert not limiter.check("u1").allowed
    clock.now += 61
    assert limiter.check("u1").allowed  # los 5 rechazos no gastaron el día


def test_internal_runs_without_user_are_not_limited(clock):
    assert all(usage_limits.consume(None, endpoint="cli").allowed for _ in range(10))


def test_limits_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("LLM_RATE_LIMIT_PER_MINUTE", "4")
    monkeypatch.setenv("LLM_RATE_LIMIT_PER_DAY", "not-a-number")
    limiter = usage_limits.build_limiter()
    assert limiter.per_minute == 4 and limiter.per_day == usage_limits.DEFAULT_PER_DAY


# --------------------------------------------------------------------------- #
# POST /agent/query
# --------------------------------------------------------------------------- #
def test_agent_query_returns_429_with_retry_after_and_skips_the_model(clock, agent_runs, as_user,
                                                                        in_memory_guardrail_log):
    client = as_user(CUSTOMER)
    statuses = [client.post("/agent/query", json={"question": QUESTION}).status_code for _ in range(4)]

    assert statuses == [200, 200, 200, 429]
    assert len(agent_runs) == 3  # la cuarta no llegó al grafo ni al LLM
    blocked = client.post("/agent/query", json={"question": QUESTION})
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 60
    assert blocked.json()["detail"] == usage_limits.RATE_LIMITED_DETAIL

    event = in_memory_guardrail_log.read()[-1]
    assert (event["guard"], event["category"], event["failure_type"], event["action"]) == (
        "rate_limit", "llm_budget", "security", "block"
    )
    assert event["rules"] == ["user_minute"] and event["user_id"] == CUSTOMER["id"]

    clock.now += 61
    assert client.post("/agent/query", json={"question": QUESTION}).status_code == 200


def test_the_budget_is_per_user(clock, agent_runs, as_user):
    client = as_user(CUSTOMER)
    for _ in range(3):
        client.post("/agent/query", json={"question": QUESTION})
    assert client.post("/agent/query", json={"question": QUESTION}).status_code == 429
    assert as_user(OTHER_CUSTOMER).post("/agent/query", json={"question": QUESTION}).status_code == 200


def test_knowledge_query_shares_the_same_budget(clock, as_user, monkeypatch):
    monkeypatch.setattr(rag_pipeline, "query", lambda question: f"respuesta a {question}")
    client = as_user(STAFF)
    statuses = [client.post("/knowledge/query", json={"question": QUESTION}).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]


def test_knowledge_query_sends_the_sanitized_question(as_user, monkeypatch):
    seen = []
    monkeypatch.setattr(rag_pipeline, "query", lambda question: seen.append(question) or "ok")
    as_user(STAFF).post("/knowledge/query", json={"question": "¿plazo​ de devolución\x07 en España?"})
    assert seen == ["¿plazo de devolución en España?"]


# --------------------------------------------------------------------------- #
# Chat por WebSocket
# --------------------------------------------------------------------------- #
def test_chat_messages_share_the_budget_and_get_a_private_chat_error(clock):
    assert [chat_router.over_llm_budget(CUSTOMER, "chat_1") for _ in range(3)] == [None, None, None]
    error = chat_router.over_llm_budget(CUSTOMER, "chat_1")
    assert error is not None
    assert error["event"] == EVENT_CHAT_ERROR
    data = ChatErrorData.model_validate(error["data"])  # el código nuevo es parte del contrato
    assert data.code == "rate_limited" and "Reintenta en" in data.detail
