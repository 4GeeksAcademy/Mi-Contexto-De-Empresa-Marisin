"""Evals del agente LangGraph sobre traces grabados (no ejecutan el grafo en vivo).

Los traces se graban una vez con Qdrant y el LLM reales:

    python scripts/agent_record_traces.py

y estos evals los comprueban con un solo comando:

    python -m pytest tests/pipelines/test_agent_evals.py -v

Criterios verificables sobre el trace:

* E1 — la ruta del grafo es la esperada para cada caso (incluida la condición
  de salida: sin contexto → `no_context`; pregunta vacía → `invalid_question`).
* E2 — `retrieve` se ejecuta una sola vez y antes que `generate_answer`, y la
  generación recibe el contexto que produjo `retrieve`.
* E3 — fuera de alcance: no se llama al LLM y la respuesta es la honesta.
* E4 — pregunta vacía: no se llega a recuperar.
* E5 — **anclaje**: la respuesta usa los documentos esperados de la base de
  conocimiento del Hito 7, incluye el dato clave y no inventa cifras.
* E6 — cada transición de estado quedó guardada como checkpoint.
"""

import json
from pathlib import Path

import pytest

from data.pipelines import rag as rag_pipeline
from services.agent import nodes

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "data" / "eval" / "agent-eval-cases.json").read_text(encoding="utf-8"))["cases"]
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "agent_traces"


def by_kind(*kinds):
    return [pytest.param(case, id=case["id"]) for case in CASES if case["kind"] in kinds]


def load_recorded_trace(case):
    path = FIXTURES_DIR / f"{case['id']}.json"
    if not path.is_file():
        pytest.fail(
            f"Falta el trace grabado {path.relative_to(ROOT)}. "
            "Grábalo con `python scripts/agent_record_traces.py` (Qdrant y .env del Hito 7)."
        )
    trace = json.loads(path.read_text(encoding="utf-8"))
    assert trace["question"] == case["question"], "trace desactualizado: vuelve a grabarlo"
    return trace


def event(trace, node):
    return next(e for e in trace["events"] if e["node"] == node)


def retrieved_context(trace):
    return event(trace, "retrieve")["output"]["context"]


@pytest.mark.parametrize("case", by_kind("grounding", "out_of_scope", "invalid"))
def test_e1_the_graph_takes_the_expected_route(case):
    trace = load_recorded_trace(case)
    assert trace["status"] == case["expected_status"]
    assert trace["path"] == case["expected_path"]
    assert all(e["status"] == "ok" for e in trace["events"])


@pytest.mark.parametrize("case", by_kind("grounding"))
def test_e2_retrieve_runs_once_and_before_generation(case):
    trace = load_recorded_trace(case)
    path = trace["path"]
    assert path.count("retrieve") == 1
    assert path.index("retrieve") < path.index("generate_answer")
    assert event(trace, "generate_answer")["input"]["context_chunks"] == len(retrieved_context(trace))


@pytest.mark.parametrize("case", by_kind("out_of_scope"))
def test_e3_out_of_scope_answers_honestly_without_the_llm(case):
    trace = load_recorded_trace(case)
    assert retrieved_context(trace) == []
    assert "generate_answer" not in trace["path"]
    assert trace["answer"] == nodes.NO_CONTEXT_ANSWER


@pytest.mark.parametrize("case", by_kind("invalid"))
def test_e4_empty_question_never_retrieves(case):
    trace = load_recorded_trace(case)
    assert "retrieve" not in trace["path"]
    assert trace["answer"] == nodes.INVALID_QUESTION_ANSWER


@pytest.mark.parametrize("case", by_kind("grounding"))
def test_e5_answer_is_grounded_in_the_briefing_knowledge_base(case):
    trace = load_recorded_trace(case)
    context = retrieved_context(trace)
    answer = trace["answer"]

    sources = {chunk["source_document"] for chunk in context}
    assert set(case["expected_sources"]) <= sources
    for term in case["answer_must_include"]:
        assert term.lower() in answer.lower(), f"falta '{term}' en la respuesta"
    assert rag_pipeline.unsupported_figures(answer, context, trace["question"]) == []
    assert "Fuente:" in answer


@pytest.mark.parametrize("case", by_kind("grounding", "out_of_scope", "invalid"))
def test_e6_every_transition_was_checkpointed(case):
    trace = load_recorded_trace(case)
    steps = [checkpoint["step"] for checkpoint in trace["checkpoints"]]
    assert steps == list(range(-1, len(trace["path"]) + 1))
    assert trace["checkpoints"][-1]["next"] == []
    assert trace["checkpoints"][-1]["values"]["status"] == case["expected_status"]
