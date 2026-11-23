"""Endpoints de recepción de RFPs (`services/rfp/router.py`, Hito 9 · Partes 1 y 2).

El `POST` responde 202 sin esperar a los agentes; el pipeline se dispara en
segundo plano (el `TestClient` ejecuta la tarea de fondo al terminar la
petición). Se usa un almacén en memoria y un directorio temporal para el PDF.
La Parte 2 se encadena tras la Parte 1 y se relanza con `POST /rfp/tickets/{id}/drafts`.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from data.pipelines.rfp_intake import config as rfp_config
from data.pipelines.rfp_intake import runner
from data.pipelines.rfp_intake.drafting import config as drafting_config
from data.pipelines.rfp_intake.drafting import runner as drafting_runner
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
    """Recorrido real de la Parte 1: POST → tarea de fondo → GET con el análisis por departamento."""
    pytest.importorskip("langgraph")
    from data.pipelines.rfp_intake import convert

    monkeypatch.setattr(drafting_config, "AUTO_DRAFT", False)  # solo la Parte 1
    markdown = (Path(__file__).parent / "pipelines" / "fixtures" / "rfp" / "trackflow-request-2.md").read_text(encoding="utf-8")
    monkeypatch.setattr(convert, "pdf_to_markdown", lambda path: markdown)

    ticket_id = upload(client, filename="trackflow-request-2.pdf").json()["ticket_id"]
    detail = client.get(f"/rfp/tickets/{ticket_id}").json()

    assert detail["status"] == "analisis_completo"
    assert [s["department_id"] for s in detail["sections"]] == ["warehouse", "lastmile"]
    assert detail["handoff"]["ticket_id"] == ticket_id
    assert detail["metadata"]["currency"] == "USD"


# --------------------------------------------------------------------------- #
# Parte 2: borradores y evaluación
# --------------------------------------------------------------------------- #
def test_upload_queues_part2_after_part1(client, store, calls, monkeypatch):
    chained = []
    monkeypatch.setattr(drafting_runner, "draft_if_ready_safely", lambda ticket_id, store, **kw: chained.append(ticket_id))

    ticket_id = upload(client).json()["ticket_id"]

    assert calls == [ticket_id]
    assert chained == [ticket_id]  # después de la Parte 1, en la misma cola de tareas de fondo


def ready_for_drafting(store):
    """Ticket como lo deja la Parte 1: `analisis_completo` + handoff + `ready_for_drafting`."""
    ticket_id = store.create_ticket(
        rfp_id="rfp-luna", raw_pdf_path="data/raw/rfp/luna.pdf", original_filename="luna.pdf",
        file_sha256="c" * 64, file_size_bytes=100, uploaded_by="1",
    )["ticket_id"]
    department = {"department_id": "warehouse", "department_name": "Warehouse Operations", "responsible": "Ana Whitfield",
                  "key_aspects": [], "open_questions": []}
    store.save_section(ticket_id, {**department, "excerpts": [], "source": "rules", "warnings": []})
    store.complete(ticket_id, {
        "contract": rfp_config.HANDOFF_CONTRACT, "ticket_id": ticket_id, "ready_for_drafting": True,
        "client": {"name": "Luna Cosmetics", "country": "United States", "currency": "USD"},
        "departments": [{**department, "ask": "Pedir a Ana Whitfield"}], "conflicts": [],
    })
    return ticket_id


def test_regenerate_drafts_answers_202_and_claims_the_ticket(client, store, monkeypatch):
    launched = []
    monkeypatch.setattr(drafting_runner, "draft_ticket_safely", lambda ticket_id, store, **kw: launched.append((ticket_id, kw)))
    ticket_id = ready_for_drafting(store)

    response = client.post(f"/rfp/tickets/{ticket_id}/drafts")

    assert response.status_code == 202
    assert response.json() == {
        "ticket_id": ticket_id, "status": "generando_borrador", "stage": "generando_secciones",
        "status_url": f"/rfp/tickets/{ticket_id}",
    }
    assert launched == [(ticket_id, {"claimed": True})]
    assert client.post(f"/rfp/tickets/{ticket_id}/drafts").status_code == 409  # ya se está generando


def test_regenerate_drafts_refuses_discarded_or_unknown_tickets(client, store, calls):
    ticket_id = upload(client).json()["ticket_id"]
    store.discard(ticket_id)

    refused = client.post(f"/rfp/tickets/{ticket_id}/drafts")

    assert refused.status_code == 409
    assert "descartado" in refused.json()["detail"]
    assert client.post("/rfp/tickets/999/drafts").status_code == 404


def test_the_background_pipeline_chains_part1_and_part2(client, store, monkeypatch):
    """Recorrido real: POST → Parte 1 → Parte 2 → GET con borradores y EvaluationResult."""
    pytest.importorskip("langgraph")
    from data.pipelines.rfp_intake import convert

    monkeypatch.setattr(drafting_config, "AUTO_DRAFT", True)
    markdown = (Path(__file__).parent / "pipelines" / "fixtures" / "rfp" / "trackflow-request-1.md").read_text(encoding="utf-8")
    monkeypatch.setattr(convert, "pdf_to_markdown", lambda path: markdown)

    ticket_id = upload(client, filename="trackflow-request-1.pdf").json()["ticket_id"]
    detail = client.get(f"/rfp/tickets/{ticket_id}").json()

    assert detail["status"] == "en_evaluación"
    assert detail["stage"] == "borradores_listos"
    assert detail["ready_for_approval"] is True
    assert detail["drafting_handoff"]["contract"] == "trackflow.rfp_drafting.handoff/v1"
    assert detail["drafting_handoff"]["currency"] == "EUR"
    for section in detail["sections"]:
        assert section["draft_status"] == "evaluacion_superada"
        assert "EUR" in section["draft_content"]
        assert set(section["evaluation_results"]) >= {
            "readability", "relevance", "compliance", "overall_pass", "feedback_for_generator",
        }
