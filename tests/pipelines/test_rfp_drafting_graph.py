"""Grafo `rfp_drafting` y ciclo generador-evaluador `rfp_section_loop` (Parte 2).

Cubre: éxito a la primera, fallo → feedback → corrección, límite de
iteraciones agotado (`needs_human_review` con el último borrador y su
`EvaluationResult`), evaluadores en paralelo con su payload mínimo y
departamentos que no se bloquean entre sí.
"""

import pytest

pytest.importorskip("langgraph")

from data.pipelines.rfp_intake.drafting import config, generators, graph, nodes  # noqa: E402
from data.pipelines.rfp_intake.drafting import handoff as contract  # noqa: E402
from data.pipelines.rfp_intake.drafting.reporter import RecordingReporter  # noqa: E402
from rfp_helpers import FORMAL, INFORMAL, ScriptedLLM, offline_handoff, offline_llm  # noqa: E402


def run(handoff, llm, reporter=None):
    return graph.build_graph(llm, reporter).invoke({"ticket_id": handoff["ticket_id"], "handoff": handoff, "sections": []})


def by_department(output):
    return {section["department_id"]: section for section in output["sections"]}


def template(fixture, department_id):
    handoff = offline_handoff(fixture, 1)
    context = next(c for c in contract.drafting_inputs(handoff) if c.department_id == department_id)
    return generators.generator_for(department_id).template(context)


def test_the_graphs_are_dedicated_and_have_the_loop_nodes():
    section_nodes = set(graph.build_section_graph().get_graph().nodes)
    ticket_nodes = set(graph.build_graph().get_graph().nodes)

    assert set(graph.SECTION_NODE_NAMES) <= section_nodes
    assert set(graph.NODE_NAMES) <= ticket_nodes
    assert not ticket_nodes & {"classify_document", "department_worker", "retrieve", "generate_answer"}


def test_every_section_passes_at_the_first_iteration_with_the_templates():
    reporter = RecordingReporter()

    final = run(offline_handoff(INFORMAL, 2), offline_llm, reporter)

    output = final["output"]
    sections = by_department(output)
    assert output["contract"] == config.OUTPUT_CONTRACT
    assert output["status"] == config.STATUS_EVALUATING
    assert output["needs_human_review"] == []
    assert list(sections) == ["warehouse", "lastmile"]
    for section in sections.values():
        assert section["draft_status"] == config.SECTION_PASSED
        assert section["iterations"] == 1
        assert section["provisional"] is False
        assert section["evaluation_result"]["overall_pass"] is True
    assert output["metrics"]["avg_iterations"] == 1
    assert ("finished", "lastmile", config.SECTION_PASSED) in reporter.events


def test_a_failing_section_goes_back_to_its_generator_with_the_feedback_and_then_passes():
    good = template(FORMAL, "reverse")
    bad = good.replace("72 horas desde que llega al almacén", "24 horas desde que llega al almacén")
    answers = iter([bad, good])
    llm = ScriptedLLM(draft_reverse=lambda user: next(answers), draft_warehouse=RuntimeError("sin LLM"))

    final = run(offline_handoff(FORMAL, 1), llm)

    reverse = by_department(final["output"])["reverse"]
    assert reverse["draft_status"] == config.SECTION_PASSED
    assert reverse["iterations"] == 2
    first, second = reverse["evaluation_history"]
    assert first["overall_pass"] is False and first["violations"] == [config.RULE_RETURNS_48H]
    assert second["overall_pass"] is True
    retry_prompt = [user for role, user in llm.calls if role == "draft_reverse"][1]
    assert "[returns-min-48h]" in retry_prompt  # el feedback concreto llega al generador
    assert "24 horas desde que llega al almacén" in retry_prompt  # junto a su borrador anterior


def test_exhausting_the_limit_keeps_the_last_draft_and_marks_needs_human_review():
    bad = template(FORMAL, "reverse").replace("72 horas", "24 horas")
    llm = ScriptedLLM(draft_reverse=bad, draft_warehouse=RuntimeError("sin LLM"))
    reporter = RecordingReporter()

    final = run(offline_handoff(FORMAL, 1), llm, reporter)

    output = final["output"]
    sections = by_department(output)
    reverse = sections["reverse"]
    assert output["status"] == config.STATUS_NEEDS_REVIEW
    assert output["needs_human_review"] == ["reverse"]
    assert reverse["draft_status"] == config.SECTION_NEEDS_REVIEW
    assert reverse["provisional"] is True
    assert reverse["iterations"] == config.MAX_ITERATIONS
    assert len(reverse["evaluation_history"]) == config.MAX_ITERATIONS
    assert reverse["draft_content"] == bad.strip()  # se conserva el último borrador
    assert reverse["evaluation_result"]["compliance"]["pass"] is False
    assert reverse["evaluation_result"]["iteration"] == config.MAX_ITERATIONS
    # El otro departamento no queda bloqueado ni arrastrado:
    assert sections["warehouse"]["draft_status"] == config.SECTION_PASSED
    assert sections["warehouse"]["iterations"] == 1
    assert ("finished", "reverse", config.SECTION_NEEDS_REVIEW) in reporter.events


def test_each_evaluator_receives_only_what_it_needs():
    handoff = offline_handoff(FORMAL, 1)
    context = contract.drafting_inputs(handoff)[0]
    state = {
        "department_id": context.department_id, "iteration": 1, "context": context.model_dump(mode="json"),
        "sources": contract.anchor_sources(context), "draft": {"content": "texto", "source": "rules"},
    }

    sends = {send.node: send.arg for send in nodes.evaluator_sends(state)}

    assert set(sends) == set(nodes.EVALUATOR_NODES)
    assert set(sends[nodes.NODE_READABILITY]) == {"department_id", "iteration", "content"}
    assert set(sends[nodes.NODE_RELEVANCE]) == {
        "department_id", "iteration", "content", "client_name", "key_aspects", "open_questions",
    }
    assert set(sends[nodes.NODE_COMPLIANCE]) == {"department_id", "iteration", "content", "currency", "sources"}


def test_the_judge_rejects_results_from_another_iteration():
    handoff = offline_handoff(FORMAL, 1)
    context = contract.drafting_inputs(handoff)[0]
    stale = {"pass": True, "iteration": 1}

    with pytest.raises(RuntimeError, match="iteración 2"):
        nodes.judge({
            "department_id": context.department_id, "iteration": 2, "context": context.model_dump(mode="json"),
            "draft": {"content": "x", "source": "rules"},
            "checks": {"readability": stale, "relevance": stale, "compliance": stale},
        })


def test_a_handoff_without_departments_is_rejected():
    handoff = offline_handoff(FORMAL, 1)
    handoff["departments"] = []

    with pytest.raises(contract.HandoffError):
        run(handoff, offline_llm)
