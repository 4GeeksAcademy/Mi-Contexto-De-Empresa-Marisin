"""Persistencia de la Parte 2 en `SqlRfpStore` (PostgreSQL en producción) contra SQLite en memoria.

Borradores, `evaluation_results` (último `EvaluationResult`), historial por
iteración, estado de cada sección y handoff a la Parte 3: lo que añade
`services/sql/004_rfp_drafting.sql`.
"""

import pytest

pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402

from data.pipelines.rfp_intake import config as intake_config  # noqa: E402
from data.pipelines.rfp_intake.drafting import config  # noqa: E402
from data.pipelines.rfp_intake.sql_store import RFP_TABLES, SqlRfpStore  # noqa: E402
from data.pipelines.rfp_intake.store import NotDraftable  # noqa: E402
from rfp_helpers import FORMAL, ticket_ready_for_drafting  # noqa: E402

EVALUATION = {
    "section_id": "1:warehouse", "department_id": "warehouse", "iteration": 1,
    "readability": {"pass": True, "score": 62.1, "details": {}},
    "relevance": {"pass": True, "missing_aspects": [], "details": {}},
    "compliance": {"pass": False, "rule_ids": list(config.COMPLIANCE_RULES), "violations": [
        {"rule_id": config.RULE_DISCOUNT_TABLE, "detail": "Falta la tabla de descuentos por volumen.", "evidence": ""},
    ]},
    "overall_pass": False, "feedback_for_generator": "- [volume-discount-table] Añade la tabla.",
    "evaluated_at": "2026-11-23T10:00:00+00:00",
}


@pytest.fixture
def store():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=RFP_TABLES)
    yield SqlRfpStore(engine)
    engine.dispose()


def test_the_queue_and_the_atomic_claim(store):
    ticket_id = ticket_ready_for_drafting(store, FORMAL)

    assert [t["ticket_id"] for t in store.list_ready_for_drafting()] == [ticket_id]
    claimed = store.claim_for_drafting(ticket_id)

    assert claimed["status"] == config.STATUS_GENERATING
    assert claimed["stage"] == config.STAGE_GENERATING
    assert claimed["ready_for_drafting"] is False
    assert store.list_ready_for_drafting() == []
    with pytest.raises(NotDraftable):
        store.claim_for_drafting(ticket_id)  # un segundo proceso no lo toma


def test_drafts_evaluations_and_history_are_persisted(store):
    ticket_id = ticket_ready_for_drafting(store, FORMAL)
    store.claim_for_drafting(ticket_id)

    store.save_section_draft(ticket_id, "warehouse", draft_status=config.SECTION_GENERATING, iterations=1)
    store.save_section_draft(ticket_id, "warehouse", draft_status=config.SECTION_EVALUATING,
                             draft_content="## Propuesta económica — Warehouse", draft_source="llm", iterations=1)
    store.set_drafting_progress(ticket_id, config.STATUS_EVALUATING, config.STAGE_EVALUATING)
    store.save_section_draft(ticket_id, "warehouse", evaluation_results=EVALUATION,
                             history_entry={"iteration": 1, "overall_pass": False})
    store.save_section_draft(ticket_id, "warehouse", evaluation_results={**EVALUATION, "iteration": 2},
                             history_entry={"iteration": 2, "overall_pass": False})
    store.save_section_draft(ticket_id, "warehouse", draft_status=config.SECTION_NEEDS_REVIEW, iterations=2)

    ticket = store.get_ticket(ticket_id)
    warehouse = next(s for s in ticket["sections"] if s["department_id"] == "warehouse")
    assert ticket["status"] == config.STATUS_EVALUATING
    assert warehouse["draft_content"].startswith("## Propuesta económica")
    assert warehouse["draft_source"] == "llm"
    assert warehouse["draft_status"] == config.SECTION_NEEDS_REVIEW
    assert warehouse["iterations"] == 2
    assert warehouse["evaluation_results"]["iteration"] == 2
    assert warehouse["evaluation_results"]["compliance"]["pass"] is False
    assert [entry["iteration"] for entry in warehouse["evaluation_history"]] == [1, 2]
    assert warehouse["approval_status"] is None  # Parte 3


def test_complete_drafting_stores_the_part3_handoff(store):
    ticket_id = ticket_ready_for_drafting(store, FORMAL)
    store.claim_for_drafting(ticket_id)
    output = {"contract": config.OUTPUT_CONTRACT, "status": config.STATUS_NEEDS_REVIEW,
              "ready_for_approval": True, "needs_human_review": ["reverse"], "sections": []}

    store.complete_drafting(ticket_id, output)

    ticket = store.get_ticket(ticket_id)
    assert ticket["status"] == config.STATUS_NEEDS_REVIEW
    assert ticket["stage"] == config.STAGE_DRAFTS_READY
    assert ticket["ready_for_approval"] is True
    assert ticket["drafting_handoff"]["needs_human_review"] == ["reverse"]


def test_a_forced_regeneration_clears_the_previous_drafts(store):
    ticket_id = ticket_ready_for_drafting(store, FORMAL)
    store.claim_for_drafting(ticket_id)
    store.save_section_draft(ticket_id, "reverse", draft_content="viejo", evaluation_results=EVALUATION,
                             history_entry={"iteration": 1}, draft_status=config.SECTION_PASSED, iterations=1)
    store.complete_drafting(ticket_id, {"status": config.STATUS_EVALUATING, "ready_for_approval": True})

    store.claim_for_drafting(ticket_id, force=True)

    reverse = next(s for s in store.get_ticket(ticket_id)["sections"] if s["department_id"] == "reverse")
    assert reverse["draft_content"] is None
    assert reverse["evaluation_results"] is None
    assert reverse["evaluation_history"] == []
    assert reverse["iterations"] == 0
    assert store.get_ticket(ticket_id)["drafting_handoff"] is None


def test_a_discarded_ticket_never_enters_part2(store):
    ticket = store.create_ticket(
        rfp_id="pitch", raw_pdf_path="data/raw/rfp/pitch.pdf", original_filename="pitch.pdf",
        file_sha256="b" * 64, file_size_bytes=10, uploaded_by="1",
    )
    store.discard(ticket["ticket_id"])

    with pytest.raises(NotDraftable):
        store.claim_for_drafting(ticket["ticket_id"], force=True)
    assert store.get_ticket(ticket["ticket_id"])["status"] == intake_config.STATUS_DISCARDED
