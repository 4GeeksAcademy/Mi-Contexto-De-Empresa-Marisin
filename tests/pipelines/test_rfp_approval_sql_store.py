"""Persistencia de la Parte 3 en `SqlRfpStore` (PostgreSQL en producción) contra SQLite en memoria.

Aprobación por sección (`approval_status`, `approver`, `approved_at`, rondas e
historial), cola `ready_for_approval`, documento final (`rfp_final_documents`)
y traza (`rfp_trace_events`): lo que añade `services/sql/005_rfp_approval.sql`.
"""

import pytest

pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402

from data.pipelines.rfp_intake.approval import config  # noqa: E402
from data.pipelines.rfp_intake.sql_store import RFP_TABLES, SqlRfpStore  # noqa: E402
from data.pipelines.rfp_intake.store import NotApprovable  # noqa: E402
from rfp_helpers import FORMAL, ticket_ready_for_drafting  # noqa: E402

DRAFTING_OUTPUT = {
    "contract": "trackflow.rfp_drafting.handoff/v1", "status": "en_evaluación", "ready_for_approval": True,
    "currency": "EUR", "needs_human_review": [], "sections": [{"department_id": "warehouse"}],
}


@pytest.fixture
def store():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=RFP_TABLES)
    yield SqlRfpStore(engine)
    engine.dispose()


def drafted(store):
    ticket_id = ticket_ready_for_drafting(store, FORMAL)
    store.claim_for_drafting(ticket_id)
    store.complete_drafting(ticket_id, DRAFTING_OUTPUT)
    return ticket_id


def test_the_approval_queue_is_claimed_atomically_once(store):
    ticket_id = drafted(store)
    assert [t["ticket_id"] for t in store.list_ready_for_approval()] == [ticket_id]

    claimed = store.claim_for_approval(ticket_id)

    assert (claimed["status"], claimed["stage"], claimed["ready_for_approval"]) == (
        config.STATUS_AWAITING, config.STAGE_AWAITING, False)
    assert store.list_ready_for_approval() == []
    with pytest.raises(NotApprovable, match="ya está esperando"):
        store.claim_for_approval(ticket_id)
    assert store.claim_for_approval(ticket_id, force=True)["status"] == config.STATUS_AWAITING


def test_section_approval_fields_and_history_are_persisted(store):
    ticket_id = drafted(store)
    store.claim_for_approval(ticket_id)

    store.save_section_approval(ticket_id, "warehouse", approval_status=config.APPROVAL_PENDING, approval_round=0,
                                approval_requested_at="2026-11-26T10:00:00+00:00")
    store.save_section_approval(
        ticket_id, "warehouse", approval_status=config.APPROVAL_APPROVED, approver="Ana Whitfield",
        approved_at="2026-11-26T10:30:00+00:00", approval_round=1,
        decision_entry={"approval_status": "aprobada", "approver": "Ana Whitfield"},
    )

    warehouse = next(s for s in store.get_ticket(ticket_id)["sections"] if s["department_id"] == "warehouse")
    assert warehouse["approval_status"] == "aprobada" and warehouse["approver"] == "Ana Whitfield"
    assert warehouse["approved_at"].isoformat().startswith("2026-11-26T10:30")
    assert warehouse["approval_round"] == 1 and warehouse["approval_history"] == [
        {"approval_status": "aprobada", "approver": "Ana Whitfield"}]


def test_the_final_document_and_the_trace_round_trip(store):
    ticket_id = drafted(store)
    store.claim_for_approval(ticket_id)
    store.append_trace(ticket_id, {"graph": config.GRAPH_NAME, "node": "load_drafts", "agent": "approval_coordinator",
                                   "status": "ok", "input": {"ticket_id": ticket_id}, "output": {},
                                   "started_at": "2026-11-26T10:00:00+00:00", "finished_at": "2026-11-26T10:00:01+00:00"})
    store.append_trace(ticket_id, {"graph": config.DEPARTMENT_GRAPH_NAME, "node": "human_approval",
                                   "agent": "humano: Ana Whitfield", "status": "interrupted",
                                   "thread_id": f"rfp-{ticket_id}:warehouse", "department_id": "warehouse",
                                   "input": {}, "output": {"waiting_for": []}, "finished_at": "2026-11-26T10:00:02+00:00"})

    store.save_final_document(ticket_id, {
        "contract": config.DOCUMENT_CONTRACT, "ticket_id": ticket_id, "client_name": "ModaViva", "currency": "EUR",
        "sections": [{"department_id": "warehouse"}], "arbitrations": [], "metrics": {"sections": 1},
        "markdown": "# Propuesta", "delivered_to": "Ventas (Miguel Torres)", "generated_at": "2026-11-26T11:00:00+00:00",
    })

    saved = store.get_ticket(ticket_id)
    assert (saved["status"], saved["stage"]) == (config.STATUS_DONE, config.STAGE_DONE)
    document = store.get_final_document(ticket_id)
    assert document["markdown"] == "# Propuesta" and document["currency"] == "EUR"
    trace = store.list_trace(ticket_id)
    assert [(e["node"], e["status"]) for e in trace] == [("load_drafts", "ok"), ("human_approval", "interrupted")]
    assert trace[1]["thread_id"] == f"rfp-{ticket_id}:warehouse"
    with pytest.raises(NotApprovable, match="terminado"):
        store.claim_for_approval(ticket_id, force=True)


def test_relaunching_part2_clears_the_approval_and_the_final_document(store):
    ticket_id = drafted(store)
    store.claim_for_approval(ticket_id)
    store.save_section_approval(ticket_id, "warehouse", approval_status=config.APPROVAL_REJECTED, approval_comment="no")
    store.set_approval_progress(ticket_id, config.STAGE_REJECTED)

    store.claim_for_drafting(ticket_id, force=True)

    warehouse = next(s for s in store.get_ticket(ticket_id)["sections"] if s["department_id"] == "warehouse")
    assert warehouse["approval_status"] is None and warehouse["approval_history"] == []
