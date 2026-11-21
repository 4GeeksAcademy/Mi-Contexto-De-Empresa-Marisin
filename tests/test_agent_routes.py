"""`POST /agent/query` y `GET /agent/traces/{run_id}`: el endpoint solo invoca el grafo."""

import pytest
from fastapi.testclient import TestClient

from data.pipelines import rag as rag_pipeline
from services.agent import mcp_client, nodes, routing
from services.api.main import app
from services.api.security import get_current_user

CONTEXT = [{"source_document": "sla-delivery", "section": "SLA de Entrega", "text": "Envío estándar: 3 a 5 días hábiles."}]
TICKET = {
    "id": "3", "title": "Caja aplastada", "description": "d", "category": "DAMAGE", "status": "open",
    "origin": "customer", "branch": "Zaragoza",
    "created_at": "2026-11-10T09:00:00+00:00", "updated_at": "2026-11-15T12:00:00+00:00",
}


def fake_mcp(tool_name, arguments):
    if tool_name == "incidents_get" and arguments == {"incident_id": 3}:
        return TICKET
    raise mcp_client.McpUnavailable("timeout: el servidor MCP no respondió en 4 s")


def no_llm(question):
    raise RuntimeError("sin LLM en los tests")


def as_user(role):
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_active": True, "role": role}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TRACE_DIR", str(tmp_path))
    monkeypatch.setattr(rag_pipeline, "retrieve", lambda q: CONTEXT if "envío" in q.lower() else [])
    monkeypatch.setattr(rag_pipeline, "generate_answer", lambda q, c: "De 3 a 5 días hábiles.")
    monkeypatch.setattr(rag_pipeline, "query", lambda *_: pytest.fail("el agente no debe usar query()"))
    monkeypatch.setattr(routing, "classify_with_llm", no_llm)
    monkeypatch.setattr(mcp_client, "call_tool", fake_mcp)
    as_user("user")
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_returns_run_id_status_answer_and_sources_only(client):
    response = client.post("/agent/query", json={"question": "¿Cuánto tarda un envío estándar?"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"run_id", "status", "answer", "sources"}
    assert body["status"] == "answered"
    assert body["answer"] == "De 3 a 5 días hábiles."
    assert body["sources"] == ["rag"]


def test_ticket_question_is_answered_by_the_incidents_tool(client):
    body = client.post("/agent/query", json={"question": "¿En qué estado está el ticket 3?"}).json()
    assert body["status"] == "answered"
    assert body["sources"] == ["incidents"]
    assert "El ticket 3 «Caja aplastada» está abierto" in body["answer"]


def test_unavailable_tool_is_a_200_with_an_honest_answer(client):
    body = client.post("/agent/query", json={"question": "¿En qué estado está el ticket 8?"}).json()
    assert body["status"] == "tool_fallback"
    assert body["answer"].startswith("No he podido confirmar el estado del ticket 8")


def test_question_without_context_gets_the_honest_answer(client):
    body = client.post("/agent/query", json={"question": "¿Cuál es la capital de Francia?"}).json()
    assert body["status"] == "no_context"
    assert body["answer"] == nodes.NO_CONTEXT_ANSWER


def test_empty_question_is_rejected_by_the_graph_with_a_clear_message(client):
    response = client.post("/agent/query", json={"question": "   "})
    assert response.status_code == 422
    assert response.json() == {"detail": nodes.INVALID_QUESTION_ANSWER}


def test_unknown_fields_are_rejected(client):
    assert client.post("/agent/query", json={"question": "hola", "k": 10}).status_code == 422


def test_a_failing_node_returns_a_clear_503_without_internals(client, monkeypatch):
    def boom(question, context):
        raise RuntimeError("Traceback: secreto interno del gateway")

    monkeypatch.setattr(rag_pipeline, "generate_answer", boom)
    response = client.post("/agent/query", json={"question": "¿Cuánto tarda un envío estándar?"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail.startswith("El agente de soporte no ha podido completar la consulta.")
    assert "Referencia:" in detail
    assert "Traceback" not in detail and "RuntimeError" not in detail and "secreto" not in detail


def test_trace_of_a_run_is_queryable_by_admin_or_manager(client):
    run_id = client.post("/agent/query", json={"question": "¿Cuánto tarda un envío estándar?"}).json()["run_id"]

    as_user("manager")
    trace = client.get(f"/agent/traces/{run_id}")

    assert trace.status_code == 200
    assert trace.json()["path"] == ["receive_question", "route_question", "retrieve", "generate_answer", "compose_answer"]
    assert trace.json()["sources"] == ["rag"]
    assert trace.json()["checkpoints"]


def test_trace_is_forbidden_for_regular_users_and_404_when_missing(client):
    run_id = client.post("/agent/query", json={"question": "¿Cuánto tarda un envío estándar?"}).json()["run_id"]
    assert client.get(f"/agent/traces/{run_id}").status_code == 403

    as_user("admin")
    assert client.get("/agent/traces/00000000-0000-4000-8000-000000000000").status_code == 404
    assert client.get("/agent/traces/no-es-un-uuid").status_code == 422


def test_requires_an_authenticated_user():
    response = TestClient(app).post("/agent/query", json={"question": "¿Cuánto tarda un envío estándar?"})
    assert response.status_code == 401
