"""Endpoints de recepción de RFPs (`services/rfp/router.py`, Hito 9 · Parte 1).

El `POST` responde 202 sin esperar a los agentes; el pipeline se dispara en
segundo plano (el `TestClient` ejecuta la tarea de fondo al terminar la
petición). Se usa un almacén en memoria y un directorio temporal para el PDF.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from data.pipelines.rfp_intake import config as rfp_config
from data.pipelines.rfp_intake import runner
from data.pipelines.rfp_intake.store import InMemoryRfpStore
from services.api.main import app
from services.api.security import get_current_user
from services.rfp import router as rfp_router

PDF = b"%PDF-1.7\n1 0 obj << >> endobj\ntrailer << >>\n%%EOF\n"


@pytest.fixture
def store():
    return InMemoryRfpStore()


@pytest.fixture
def calls(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "process_ticket_safely", lambda ticket_id, store, **kw: calls.append(ticket_id))
    return calls


@pytest.fixture
def client(store, tmp_path, monkeypatch):
    monkeypatch.setattr(rfp_config, "RAW_DIR", tmp_path / "raw" / "rfp")
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_active": True, "role": "user"}
    app.dependency_overrides[rfp_router.get_rfp_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(rfp_router.get_rfp_store, None)


def upload(client, content=PDF, filename="ModaViva RFP.pdf", content_type="application/pdf"):
    return client.post(f"/rfp/tickets?filename={filename}", content=content, headers={"Content-Type": content_type})


def test_upload_answers_202_saves_the_pdf_and_triggers_the_pipeline_in_background(client, store, calls, tmp_path):
    response = upload(client)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "analizando"
    assert body["status_url"] == f"/rfp/tickets/{body['ticket_id']}"
    assert calls == [body["ticket_id"]]
    saved = list((tmp_path / "raw" / "rfp").glob("*.pdf"))
    assert [path.name for path in saved] == [f"{body['rfp_id']}.pdf"]
    assert saved[0].read_bytes() == PDF
    assert store.get_ticket(body["ticket_id"])["original_filename"] == "ModaViva RFP.pdf"


def test_the_filename_never_decides_the_path_on_disk(client, store, calls, tmp_path):
    response = upload(client, filename="../../etc/passwd.pdf")

    assert response.status_code == 202
    ticket = store.get_ticket(response.json()["ticket_id"])
    assert ticket["original_filename"] == "passwd.pdf"
    assert Path(ticket["raw_pdf_path"]).parent == (tmp_path / "raw" / "rfp").resolve()


@pytest.mark.parametrize(
    ("content", "filename", "content_type", "status_code"),
    [
        (b"PK\x03\x04 esto es un docx", "rfp.docx", "application/pdf", 415),
        (PDF, "rfp.pdf", "application/json", 415),
        (b"", "rfp.pdf", "application/pdf", 422),
        (b"no soy un pdf", "rfp.pdf", "application/pdf", 415),
    ],
)
def test_only_pdfs_create_tickets(client, store, calls, content, filename, content_type, status_code):
    response = upload(client, content=content, filename=filename, content_type=content_type)

    assert response.status_code == status_code
    assert store.list_tickets() == []
    assert calls == []


def test_status_is_queryable_while_and_after_the_pipeline_runs(client, store, calls):
    ticket_id = upload(client).json()["ticket_id"]

    analysing = client.get(f"/rfp/tickets/{ticket_id}").json()
    store.discard(ticket_id)
    discarded = client.get(f"/rfp/tickets/{ticket_id}").json()

    assert analysing["status"] == "analizando"
    assert analysing["stale"] is False
    assert discarded["status"] == "descartado"
    assert "markdown" not in discarded


def test_list_returns_newest_first(client, calls):
    first = upload(client).json()["ticket_id"]
    second = upload(client).json()["ticket_id"]

    tickets = client.get("/rfp/tickets").json()["tickets"]

    assert [ticket["ticket_id"] for ticket in tickets] == [second, first]


def test_unknown_ticket_is_404(client):
    assert client.get("/rfp/tickets/999").status_code == 404


def test_requires_an_authenticated_user():
    assert TestClient(app).post("/rfp/tickets", content=PDF, headers={"Content-Type": "application/pdf"}).status_code == 401
    assert TestClient(app).get("/rfp/tickets").status_code == 401


def test_without_database_the_endpoints_answer_503(monkeypatch):
    monkeypatch.setattr(rfp_router, "engine", None)
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_active": True, "role": "user"}
    try:
        response = TestClient(app).get("/rfp/tickets")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert response.status_code == 503


def test_the_background_pipeline_ends_in_analysis_complete(client, store, monkeypatch):
    """Recorrido real: POST → tarea de fondo → GET con el análisis por departamento."""
    pytest.importorskip("langgraph")
    from data.pipelines.rfp_intake import convert

    markdown = (Path(__file__).parent / "pipelines" / "fixtures" / "rfp" / "trackflow-request-2.md").read_text(encoding="utf-8")
    monkeypatch.setattr(convert, "pdf_to_markdown", lambda path: markdown)

    ticket_id = upload(client, filename="trackflow-request-2.pdf").json()["ticket_id"]
    detail = client.get(f"/rfp/tickets/{ticket_id}").json()

    assert detail["status"] == "analisis_completo"
    assert [s["department_id"] for s in detail["sections"]] == ["warehouse", "lastmile"]
    assert detail["handoff"]["ticket_id"] == ticket_id
    assert detail["metadata"]["currency"] == "USD"
