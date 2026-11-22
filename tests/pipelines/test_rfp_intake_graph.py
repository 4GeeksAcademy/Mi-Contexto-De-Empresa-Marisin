"""Grafo `rfp_intake` + runner de punta a punta, con un almacén en memoria.

La conversión PDF → Markdown se sustituye por el Markdown de las muestras del
BRIEFING (los PDF no se versionan); el resto es el grafo real de LangGraph.
"""

import pytest

pytest.importorskip("langgraph")

from data.pipelines.rfp_intake import config, convert, graph, runner  # noqa: E402
from data.pipelines.rfp_intake.store import InMemoryRfpStore  # noqa: E402
from rfp_helpers import FORMAL, INFORMAL, INVALID, ScriptedLLM, load, offline_llm  # noqa: E402


@pytest.fixture
def store():
    return InMemoryRfpStore()


def new_ticket(store, monkeypatch, fixture):
    monkeypatch.setattr(convert, "pdf_to_markdown", lambda path: load(fixture))
    return store.create_ticket(
        rfp_id=f"rfp-{fixture}", raw_pdf_path=f"data/raw/rfp/{fixture}.pdf", original_filename=fixture,
        file_sha256="0" * 64, file_size_bytes=100, uploaded_by="1",
    )


def test_the_graph_is_dedicated_and_has_the_orchestrator_worker_synthesizer_nodes():
    compiled = graph.build_graph()

    nodes = set(compiled.get_graph().nodes)
    assert set(graph.NODE_NAMES) <= nodes
    assert not any(name in nodes for name in ("route_question", "retrieve", "generate_answer"))  # grafo de CX


def test_formal_rfp_ends_in_analysis_complete_with_warehouse_and_reverse(store, monkeypatch):
    ticket = new_ticket(store, monkeypatch, FORMAL)

    result = runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    saved = store.get_ticket(ticket["ticket_id"])
    assert result.outcome == "analysis_complete"
    assert saved["status"] == config.STATUS_ANALYSIS_COMPLETE
    assert saved["stage"] == config.STAGE_DONE
    assert [s["department_id"] for s in saved["sections"]] == ["warehouse", "reverse"]
    assert all(s["key_aspects"] for s in saved["sections"])
    assert saved["metadata"]["client_country"] == "Spain"
    assert saved["metadata"]["currency"] == "EUR"
    assert saved["metadata"]["readability"]["word_count"] > 0
    assert saved["ready_for_drafting"] is True
    assert saved["handoff"]["ticket_id"] == ticket["ticket_id"]
    assert result.nodes.count("department_worker") == 2


def test_informal_rfp_ends_in_analysis_complete_with_warehouse_and_lastmile(store, monkeypatch):
    ticket = new_ticket(store, monkeypatch, INFORMAL)

    runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    saved = store.get_ticket(ticket["ticket_id"])
    assert saved["status"] == config.STATUS_ANALYSIS_COMPLETE
    assert [s["department_id"] for s in saved["sections"]] == ["warehouse", "lastmile"]
    assert saved["metadata"]["currency"] == "USD"
    assert saved["metadata"]["monthly_volume"] == 5000
    assert {d["responsible"] for d in saved["handoff"]["departments"]} == {"Ana Whitfield", "Carlos Vega"}


def test_invalid_document_is_discarded_and_no_agent_after_the_classifier_runs(store, monkeypatch):
    ticket = new_ticket(store, monkeypatch, INVALID)
    llm = ScriptedLLM(classifier={"is_rfp": False, "document_type": "vendor_pitch", "confidence": 0.97,
                                  "reason": "RapidShip ofrece tarifas a TrackFlow."})

    result = runner.process_ticket(ticket["ticket_id"], store, llm=llm)

    saved = store.get_ticket(ticket["ticket_id"])
    assert result.outcome == "discarded"
    assert saved["status"] == config.STATUS_DISCARDED
    assert saved["classification"]["reason"] == "RapidShip ofrece tarifas a TrackFlow."
    assert saved["metadata"] is None and saved["sections"] == [] and saved["handoff"] is None
    assert llm.roles_called() == ["classifier"]
    assert result.nodes == ["convert_document", "classify_document", "discard_document"]


def test_workers_run_once_per_active_department_with_the_llm(store, monkeypatch):
    ticket = new_ticket(store, monkeypatch, INFORMAL)
    worker = {"key_aspects": [], "open_questions": []}
    llm = ScriptedLLM(
        classifier={"is_rfp": True, "document_type": "informal_request", "confidence": 0.9, "reason": "Pide propuesta."},
        metadata={"client_name": "Luna Cosmetics", "client_country": "United States",
                  "services_requested": ["warehousing", "last_mile"], "monthly_volume": 5000},
        orchestrator={"workstreams": [], "out_of_scope": []},
        warehouse=worker, lastmile=worker,
        synthesizer="Luna Cosmetics pide almacenamiento y última milla en USD; Ana Whitfield y Carlos Vega cotizan.",
    )

    runner.process_ticket(ticket["ticket_id"], store, llm=llm)

    roles = llm.roles_called()
    assert roles[:3] == ["classifier", "metadata", "orchestrator"]
    assert sorted(roles[3:5]) == ["lastmile", "warehouse"]
    assert roles[5:] == ["synthesizer"]
    assert "reverse" not in roles


def test_a_failure_mid_pipeline_leaves_the_ticket_analyzing_with_the_failed_stage(store, monkeypatch):
    ticket = new_ticket(store, monkeypatch, FORMAL)

    def broken_worker(*args, **kwargs):
        raise RuntimeError("worker caído")

    from data.pipelines.rfp_intake import workers

    monkeypatch.setattr(workers, "run_department_worker", broken_worker)

    result = runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    saved = store.get_ticket(ticket["ticket_id"])
    assert result.outcome == "error"
    assert saved["status"] == config.STATUS_ANALYZING  # nunca «completo» si no terminó
    assert saved["stage"] == config.STAGE_ERROR
    assert saved["error_stage"] == config.STAGE_DEPARTMENTS
    assert "worker caído" in saved["error_message"]
    assert saved["metadata"]["client_name"] == "ModaViva"  # lo ya hecho queda guardado


def test_a_conversion_failure_is_recorded_at_the_conversion_stage(store, monkeypatch):
    ticket = new_ticket(store, monkeypatch, FORMAL)

    def unreadable(path):
        raise convert.ConversionError("El PDF no contiene texto extraíble")

    monkeypatch.setattr(convert, "pdf_to_markdown", unreadable)

    runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    saved = store.get_ticket(ticket["ticket_id"])
    assert saved["error_stage"] == config.STAGE_CONVERTING
    assert "texto extraíble" in saved["error_message"]


def test_one_failed_ticket_does_not_stop_the_others(store, monkeypatch):
    broken = new_ticket(store, monkeypatch, FORMAL)
    monkeypatch.setattr(convert, "pdf_to_markdown", lambda path: (_ for _ in ()).throw(RuntimeError("roto")))
    runner.process_ticket_safely(broken["ticket_id"], store, llm=offline_llm)

    healthy = new_ticket(store, monkeypatch, INFORMAL)
    runner.process_ticket_safely(healthy["ticket_id"], store, llm=offline_llm)

    assert store.get_ticket(broken["ticket_id"])["stage"] == config.STAGE_ERROR
    assert store.get_ticket(healthy["ticket_id"])["status"] == config.STATUS_ANALYSIS_COMPLETE


def test_reprocessing_a_ticket_replaces_the_previous_analysis(store, monkeypatch):
    ticket = new_ticket(store, monkeypatch, INFORMAL)
    runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    runner.process_ticket(ticket["ticket_id"], store, llm=offline_llm)

    saved = store.get_ticket(ticket["ticket_id"])
    assert saved["status"] == config.STATUS_ANALYSIS_COMPLETE
    assert [s["department_id"] for s in saved["sections"]] == ["warehouse", "lastmile"]
