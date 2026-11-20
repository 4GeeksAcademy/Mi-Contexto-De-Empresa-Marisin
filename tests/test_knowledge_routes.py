"""`POST /knowledge/query` (Hito 7 — RAG): reutiliza `query()` y solo devuelve `answer`."""

import pytest
from fastapi.testclient import TestClient

from data.pipelines import rag as rag_pipeline
from services.api.main import app
from services.api.security import get_current_user


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_active": True, "role": "user"}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_returns_only_the_generated_answer(client, monkeypatch):
    calls = []
    monkeypatch.setattr(rag_pipeline, "query", lambda question: calls.append(question) or "Respuesta del modelo.")

    response = client.post("/knowledge/query", json={"question": "¿Cuál es la ventana de devolución estándar?"})

    assert response.status_code == 200
    assert response.json() == {"answer": "Respuesta del modelo."}
    assert calls == ["¿Cuál es la ventana de devolución estándar?"]


def test_does_not_expose_chunks_scores_or_ids(client, monkeypatch):
    monkeypatch.setattr(rag_pipeline, "query", lambda question: "ok")
    body = client.post("/knowledge/query", json={"question": "¿Qué transportista cubre Aragón rural?"}).json()
    assert set(body) == {"answer"}


def test_rejects_empty_or_unknown_fields(client, monkeypatch):
    monkeypatch.setattr(rag_pipeline, "query", lambda question: pytest.fail("no debe llamarse"))
    assert client.post("/knowledge/query", json={"question": "  "}).status_code == 422
    assert client.post("/knowledge/query", json={"question": "hola", "k": 10}).status_code == 422


def test_pipeline_failure_is_a_503_not_an_empty_answer(client, monkeypatch):
    def boom(question):
        raise RuntimeError("Qdrant caído")

    monkeypatch.setattr(rag_pipeline, "query", boom)
    response = client.post("/knowledge/query", json={"question": "¿Cuál es el SLA estándar?"})
    assert response.status_code == 503
    assert "answer" not in response.json()


def test_requires_an_authenticated_user():
    response = TestClient(app).post("/knowledge/query", json={"question": "¿Cuál es el SLA estándar?"})
    assert response.status_code == 401
