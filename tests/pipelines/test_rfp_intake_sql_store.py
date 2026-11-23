"""`SqlRfpStore` (PostgreSQL/Supabase en producción) contra un SQLite en memoria.

Mismas tablas SQLModel que crea `services/sql/003_rfp_intake.sql`: el ciclo de
vida del ticket, los metadatos y `key_aspects` por departamento se comprueban
contra una base de datos real, no contra dobles.
"""

from datetime import date

import pytest

pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402

from data.pipelines.rfp_intake import config  # noqa: E402
from data.pipelines.rfp_intake.sql_store import RFP_TABLES, SqlRfpStore  # noqa: E402


@pytest.fixture
def store():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=RFP_TABLES)
    yield SqlRfpStore(engine)
    engine.dispose()


def create(store, rfp_id="rfp-1"):
    return store.create_ticket(
        rfp_id=rfp_id, raw_pdf_path=f"data/raw/rfp/{rfp_id}.pdf", original_filename="ModaViva RFP.pdf",
        file_sha256="a" * 64, file_size_bytes=1234, uploaded_by="1",
    )


METADATA = {
    "client_name": "ModaViva", "client_reference": "MV-LOG-2026-03", "client_country": "Spain", "currency": "EUR",
    "services_requested": ["warehousing", "reverse_logistics"], "monthly_volume": None, "deadline": "2026-08-28",
    "deadline_text": "Proposal Due Date: August 28, 2026", "budget_range": None,
    "contact": {"name": "Elena Bosch", "role": None, "email": None}, "departments_needed": ["warehouse", "reverse"],
    "source": "llm", "warnings": [],
}
SECTION = {
    "department_id": "warehouse", "department_name": "Warehouse Operations", "responsible": "Ana Whitfield",
    "key_aspects": [{"topic": "SKUs", "detail": "15.000 SKUs.", "evidence": "15.000 SKUs"}],
    "open_questions": ["¿Volumen mensual?"], "excerpts": ["15.000 SKUs"], "source": "llm", "warnings": [],
}


def test_a_new_ticket_starts_analyzing(store):
    ticket = create(store)

    assert ticket["ticket_id"] == 1
    assert ticket["status"] == config.STATUS_ANALYZING
    assert ticket["stage"] == config.STAGE_RECEIVED
    assert ticket["ready_for_drafting"] is False
    assert "markdown" not in ticket


def test_full_lifecycle_persists_metadata_sections_and_handoff(store):
    ticket_id = create(store)["ticket_id"]
    store.start_processing(ticket_id)
    store.save_markdown(ticket_id, "# RFP ModaViva\n")
    store.save_classification(ticket_id, {"is_rfp": True, "reason": "Pliego formal"}, config.STAGE_METADATA)
    store.save_metadata(ticket_id, METADATA, {"word_count": 196, "estimated_tokens": 342})
    store.save_section(ticket_id, SECTION)
    store.complete(ticket_id, {"ticket_id": ticket_id, "ready_for_drafting": True, "departments": []})

    saved = store.get_ticket(ticket_id)
    assert saved["status"] == config.STATUS_ANALYSIS_COMPLETE
    assert saved["ready_for_drafting"] is True
    assert saved["markdown_chars"] == len("# RFP ModaViva\n")
    assert store.get_markdown(ticket_id) == "# RFP ModaViva\n"
    assert saved["classification"]["reason"] == "Pliego formal"
    assert saved["metadata"]["client_country"] == "Spain"
    assert saved["metadata"]["deadline"] == date(2026, 8, 28).isoformat()
    assert saved["metadata"]["readability"]["word_count"] == 196
    assert saved["sections"][0]["key_aspects"][0]["detail"] == "15.000 SKUs."
    assert saved["sections"][0]["approval_status"] is None  # Parte 3
    assert saved["handoff"]["ticket_id"] == ticket_id


def test_discard_and_failure_states(store):
    discarded = create(store, "rfp-d")["ticket_id"]
    store.discard(discarded)
    failed = create(store, "rfp-f")["ticket_id"]
    store.fail(failed, config.STAGE_CONVERTING, "ConversionError: sin texto")

    assert store.get_ticket(discarded)["status"] == config.STATUS_DISCARDED
    saved = store.get_ticket(failed)
    assert saved["status"] == config.STATUS_ANALYZING
    assert (saved["stage"], saved["error_stage"]) == (config.STAGE_ERROR, config.STAGE_CONVERTING)


def test_reprocessing_clears_the_previous_analysis_and_sections_are_unique(store):
    ticket_id = create(store)["ticket_id"]
    store.save_metadata(ticket_id, METADATA, {})
    store.save_section(ticket_id, SECTION)
    store.save_section(ticket_id, {**SECTION, "open_questions": ["¿Pallets?"]})
    assert len(store.get_ticket(ticket_id)["sections"]) == 1

    store.start_processing(ticket_id)

    saved = store.get_ticket(ticket_id)
    assert saved["metadata"] is None and saved["sections"] == []
    assert saved["stage"] == config.STAGE_CONVERTING


def test_list_tickets_is_newest_first_with_the_client_name(store):
    first = create(store, "rfp-a")["ticket_id"]
    second = create(store, "rfp-b")["ticket_id"]
    store.save_metadata(first, METADATA, {})

    listed = store.list_tickets()

    assert [t["ticket_id"] for t in listed] == [second, first]
    assert listed[1]["client_name"] == "ModaViva"
    assert listed[0]["client_name"] is None
