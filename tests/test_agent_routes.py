"""`POST /agent/query` y `GET /agent/traces/{run_id}`: el endpoint solo invoca el grafo."""

import pytest
from fastapi.testclient import TestClient

from data.pipelines import rag as rag_pipeline
from services.agent import nodes
from services.api.main import app
from services.api.security import get_current_user

CONTEXT = [{"source_document": "sla-delivery", "section": "SLA de Entrega", "text": "Envío estándar: 3 a 5 días hábiles."}]


def as_user(role):
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_active": True, "role": role}


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TRACE_DIR", str(tmp_path))
    monkeypatch.setattr(rag_pipeline, "retrieve", lambda q: CONTEXT if "envío" in q.lower() else [])
    monkeypatch.setattr(rag_pipeline, "generate_answer", lambda q, c: "De 3 a 5 días hábiles.")
    monkeypatch.setattr(rag_pipeline, "query", lambda *_: pytest.fail("el agente no debe usar query()"))
    as_user("user")
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_returns_run_id_status_and_answer_only(client):
    response = client.post("/agent/query", json={"question": "¿Cuánto tarda un envío estándar?"})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"run_id", "status", "answer"}
    assert body["status"] == "answered"
    assert body["answer"] == "De 3 a 5 días hábiles."


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
    assert trace.json()["path"] == ["receive_question", "retrieve", "generate_answer"]
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
