"""Runner de la Parte 2 sobre el almacén en memoria: consume el handoff y actualiza el ticket.

El ticket lo deja la Parte 1 en `analisis_completo` + `ready_for_drafting`;
la Parte 2 lo pasa por `generando_borrador` → `en_evaluación` →
(`needs_human_review` si alguna sección agota el límite), guardando cada
borrador y su `EvaluationResult`. Nunca vuelve a leer el PDF ni el Markdown.
"""

import pytest

pytest.importorskip("langgraph")

from data.pipelines.rfp_intake import config as intake_config  # noqa: E402
from data.pipelines.rfp_intake import convert  # noqa: E402
from data.pipelines.rfp_intake.drafting import config, generators, runner  # noqa: E402
from data.pipelines.rfp_intake.drafting import handoff as contract  # noqa: E402
from data.pipelines.rfp_intake.store import InMemoryRfpStore, NotDraftable  # noqa: E402
from rfp_helpers import FORMAL, INFORMAL, ScriptedLLM, offline_llm, ticket_ready_for_drafting  # noqa: E402


class TrackingStore(InMemoryRfpStore):
    """Registra cada cambio de estado del ticket y de sus secciones, en orden."""

    def __init__(self):
        super().__init__()
        self.ticket_states = []
        self.section_states = []

    def claim_for_drafting(self, ticket_id, *, force=False):
        ticket = super().claim_for_drafting(ticket_id, force=force)
        self.ticket_states.append((ticket["status"], ticket["stage"]))
        return ticket

    def set_drafting_progress(self, ticket_id, status, stage):
        super().set_drafting_progress(ticket_id, status, stage)
        self.ticket_states.append((status, stage))

    def save_section_draft(self, ticket_id, department_id, **changes):
        super().save_section_draft(ticket_id, department_id, **changes)
        if "draft_status" in changes:
            self.section_states.append((department_id, changes["draft_status"]))

    def complete_drafting(self, ticket_id, output):
        super().complete_drafting(ticket_id, output)
        self.ticket_states.append((output["status"], config.STAGE_DRAFTS_READY))

    def get_markdown(self, ticket_id):
        raise AssertionError("la Parte 2 no debe volver a leer el Markdown")


@pytest.fixture
def store(monkeypatch):
    def no_pdf(path):
        raise AssertionError("la Parte 2 no debe volver a convertir el PDF")

    monkeypatch.setattr(convert, "pdf_to_markdown", no_pdf)
    return TrackingStore()


def reverse_bad_llm():
    ticket_store = InMemoryRfpStore()
    ticket_id = ticket_ready_for_drafting(ticket_store, FORMAL)
    handoff = ticket_store.get_ticket(ticket_id)["handoff"]
    context = next(c for c in contract.drafting_inputs(handoff) if c.department_id == "reverse")
    bad = generators.generator_for("reverse").template(context).replace("72 horas", "24 horas")
    return ScriptedLLM(draft_reverse=bad, draft_warehouse=RuntimeError("sin LLM"))


def test_part2_consumes_the_handoff_and_reports_progress_in_real_time(store):
    ticket_id = ticket_ready_for_drafting(store, INFORMAL)

    result = runner.draft_ticket(ticket_id, store, llm=offline_llm)

    ticket = store.get_ticket(ticket_id)
    assert result.outcome == "drafts_ready"
    assert store.ticket_states[0] == (config.STATUS_GENERATING, config.STAGE_GENERATING)
    assert (config.STATUS_EVALUATING, config.STAGE_EVALUATING) in store.ticket_states
    assert store.ticket_states[-1] == (config.STATUS_EVALUATING, config.STAGE_DRAFTS_READY)
    for department_id in ("warehouse", "lastmile"):
        states = [state for dept, state in store.section_states if dept == department_id]
        assert states == [config.SECTION_GENERATING, config.SECTION_EVALUATING, config.SECTION_PASSED]
    assert ticket["status"] == config.STATUS_EVALUATING
    assert ticket["ready_for_drafting"] is False  # el ticket salió de la cola
    assert ticket["ready_for_approval"] is True
    assert ticket["drafting_handoff"]["contract"] == config.OUTPUT_CONTRACT
    for section in ticket["sections"]:
        assert section["draft_content"].startswith("## Propuesta económica")
        assert section["evaluation_results"]["overall_pass"] is True
        assert section["evaluation_results"]["readability"]["pass"] is True
        assert len(section["evaluation_history"]) == 1
        assert section["approval_status"] is None  # Parte 3


def test_an_exhausted_section_marks_the_ticket_needs_human_review_without_discarding_it(store):
    ticket_id = ticket_ready_for_drafting(store, FORMAL)

    result = runner.draft_ticket(ticket_id, store, llm=reverse_bad_llm())

    ticket = store.get_ticket(ticket_id)
    sections = {s["department_id"]: s for s in ticket["sections"]}
    assert result.outcome == "needs_human_review"
    assert ticket["status"] == config.STATUS_NEEDS_REVIEW
    assert ticket["ready_for_approval"] is True  # pasa igual a la Parte 3
    assert sections["reverse"]["draft_status"] == config.SECTION_NEEDS_REVIEW
    assert "24 horas" in sections["reverse"]["draft_content"]
    assert sections["reverse"]["evaluation_results"]["overall_pass"] is False
    assert sections["reverse"]["iterations"] == config.MAX_ITERATIONS
    assert sections["warehouse"]["draft_status"] == config.SECTION_PASSED
    assert ticket["drafting_handoff"]["needs_human_review"] == ["reverse"]
    assert [s["department_id"] for s in ticket["drafting_handoff"]["sections"]] == ["warehouse", "reverse"]


def test_only_tickets_in_the_part1_queue_start_part2(store):
    discarded = store.create_ticket(
        rfp_id="pitch", raw_pdf_path="data/raw/rfp/pitch.pdf", original_filename="pitch.pdf",
        file_sha256="1" * 64, file_size_bytes=10, uploaded_by="1",
    )["ticket_id"]
    store.discard(discarded)
    ready = ticket_ready_for_drafting(store, INFORMAL)

    with pytest.raises(NotDraftable):
        runner.draft_ticket(discarded, store, llm=offline_llm)
    assert [t["ticket_id"] for t in store.list_ready_for_drafting()] == [ready]
    runner.draft_ticket(ready, store, llm=offline_llm)
    assert store.list_ready_for_drafting() == []
    with pytest.raises(NotDraftable):  # ya pasó por la Parte 2: hace falta pedirlo explícitamente
        runner.draft_ticket(ready, store, llm=offline_llm)
    assert runner.draft_ticket(ready, store, llm=offline_llm, force=True).outcome == "drafts_ready"


def test_a_failure_leaves_stage_error_and_keeps_what_was_generated(store, monkeypatch):
    ticket_id = ticket_ready_for_drafting(store, INFORMAL)
    from data.pipelines.rfp_intake.drafting import evaluators

    def broken(content):
        raise ValueError("evaluador caído")

    monkeypatch.setattr(evaluators, "evaluate_readability", broken)

    result = runner.draft_ticket(ticket_id, store, llm=offline_llm)

    ticket = store.get_ticket(ticket_id)
    assert result.outcome == "error"
    assert ticket["stage"] == intake_config.STAGE_ERROR
    assert ticket["error_stage"] == config.STAGE_EVALUATING
    assert ticket["status"] == config.STATUS_EVALUATING  # nunca dice que terminó
    assert any(section["draft_content"] for section in ticket["sections"])  # lo generado no se pierde
    assert runner.draft_ticket(ticket_id, store, llm=offline_llm, force=True).outcome == "error"


def test_part2_chains_after_part1_only_when_the_ticket_is_ready(store, monkeypatch):
    ready = ticket_ready_for_drafting(store, INFORMAL)
    analysing = store.create_ticket(
        rfp_id="x", raw_pdf_path="data/raw/rfp/x.pdf", original_filename="x.pdf",
        file_sha256="2" * 64, file_size_bytes=10, uploaded_by="1",
    )["ticket_id"]

    runner.draft_if_ready_safely(analysing, store, llm=offline_llm)
    runner.draft_if_ready_safely(ready, store, llm=offline_llm)

    assert store.get_ticket(analysing)["status"] == intake_config.STATUS_ANALYZING
    assert store.get_ticket(ready)["stage"] == config.STAGE_DRAFTS_READY

    monkeypatch.setattr(config, "AUTO_DRAFT", False)
    other = ticket_ready_for_drafting(store, FORMAL)
    runner.draft_if_ready_safely(other, store, llm=offline_llm)
    assert store.get_ticket(other)["status"] == intake_config.STATUS_ANALYSIS_COMPLETE


def test_reprocessing_part1_clears_the_part2_results(store):
    ticket_id = ticket_ready_for_drafting(store, INFORMAL)
    runner.draft_ticket(ticket_id, store, llm=offline_llm)

    store.start_processing(ticket_id)

    ticket = store.get_ticket(ticket_id)
    assert ticket["drafting_handoff"] is None
    assert ticket["ready_for_approval"] is False
    assert ticket["sections"] == []
