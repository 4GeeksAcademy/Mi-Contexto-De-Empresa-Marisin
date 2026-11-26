"""Emisión de `rfp_ticket_created` desde el pipeline (`runner.process_ticket` → `events.emit`).

Mismo grafo y LLM fuera de línea que `test_rfp_intake_graph.py`: el evento sale
una sola vez, cuando la RFP es válida y ya tiene metadatos (estado
`analizando`); un documento descartado no emite y un listener roto no rompe
el pipeline. Aquí no interviene la API: solo el gancho de `events.py`.
"""

from __future__ import annotations

import pytest

pytest.importorskip("langgraph")

from data.pipelines.rfp_intake import config, convert, events, runner  # noqa: E402
from data.pipelines.rfp_intake.store import InMemoryRfpStore  # noqa: E402
from rfp_helpers import FORMAL, INVALID, ScriptedLLM, load, offline_llm  # noqa: E402


@pytest.fixture
def store():
    return InMemoryRfpStore()


@pytest.fixture
def received():
    received: list[tuple[str, dict]] = []
    listener = lambda event, payload: received.append((event, payload))  # noqa: E731
    unsubscribe = events.subscribe(listener)
    yield received
    unsubscribe()


def new_ticket(store, monkeypatch, fixture):
    monkeypatch.setattr(convert, "pdf_to_markdown", lambda path: load(fixture))
    return store.create_ticket(
        rfp_id=f"rfp-{fixture}", raw_pdf_path=f"data/raw/rfp/{fixture}.pdf", original_filename=fixture,
        file_sha256="0" * 64, file_size_bytes=100, uploaded_by="1",
    )


def created(received):
    return [payload for event, payload in received if event == events.EVENT_RFP_TICKET_CREATED]


def test_a_valid_rfp_emits_one_rfp_ticket_created_with_its_metadata(store, monkeypatch, received):
    ticket = new_ticket(store, monkeypatch, FORMAL)

    result = runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    assert result.outcome == "analysis_complete"
    [payload] = created(received)
    assert payload["ticket_id"] == ticket["ticket_id"]
    assert payload["rfp_id"] == ticket["rfp_id"]
    assert payload["client_name"]  # ya extraído: se emite después de save_metadata
    assert payload["client_country"] == "Spain"
    assert payload["services_requested"]
    assert payload["status"] == config.STATUS_ANALYZING
    assert payload["stage"] == config.STAGE_ORCHESTRATING
    assert payload["original_filename"] == FORMAL
    assert payload["created_at"].endswith("Z")
    assert set(payload) == {
        "ticket_id", "rfp_id", "client_name", "client_country", "services_requested", "status", "created_at",
        "stage", "original_filename",
    }


def test_the_payload_validates_against_the_sse_schema(store, monkeypatch, received):
    from services.realtime.schemas import RfpTicketCreatedEvent

    ticket = new_ticket(store, monkeypatch, FORMAL)
    runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    [payload] = created(received)
    assert RfpTicketCreatedEvent.model_validate(payload).ticket_id == ticket["ticket_id"]


def test_a_discarded_document_never_emits(store, monkeypatch, received):
    ticket = new_ticket(store, monkeypatch, INVALID)
    llm = ScriptedLLM(classifier={"is_rfp": False, "document_type": "vendor_pitch", "confidence": 0.97,
                                  "reason": "RapidShip ofrece tarifas a TrackFlow."})

    result = runner.process_ticket(ticket["ticket_id"], store, llm=llm)

    assert result.outcome == "discarded"
    assert created(received) == []


def test_a_failing_listener_does_not_break_the_pipeline(store, monkeypatch, received):
    def broken(event, payload):
        raise RuntimeError("listener roto")

    unsubscribe = events.subscribe(broken)
    try:
        ticket = new_ticket(store, monkeypatch, FORMAL)
        result = runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)
    finally:
        unsubscribe()

    assert result.outcome == "analysis_complete"
    assert store.get_ticket(ticket["ticket_id"])["status"] == config.STATUS_ANALYSIS_COMPLETE
    assert len(created(received)) == 1  # el resto de listeners sí lo recibe


def test_a_store_failure_while_notifying_does_not_break_the_pipeline(store, monkeypatch, received):
    ticket = new_ticket(store, monkeypatch, FORMAL)
    original = store.get_ticket
    calls = {"n": 0}

    def flaky_get_ticket(ticket_id):
        calls["n"] += 1
        if calls["n"] == 2:  # la lectura de _notify_ticket_created (la 1.ª es la de process_ticket)
            raise RuntimeError("base de datos caída")
        return original(ticket_id)

    monkeypatch.setattr(store, "get_ticket", flaky_get_ticket)

    result = runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    assert result.outcome == "analysis_complete"
    assert created(received) == []
