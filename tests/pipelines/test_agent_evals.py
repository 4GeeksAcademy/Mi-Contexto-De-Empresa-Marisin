"""Evals del agente LangGraph sobre traces grabados (no ejecutan el grafo en vivo).

Los traces se graban una vez con Qdrant, el LLM y la API de TrackFlow reales:

    python scripts/agent_record_traces.py

y estos evals los comprueban con un solo comando:

    python -m pytest tests/pipelines/test_agent_evals.py -v

Parte 1 — flujo y anclaje en el RAG:

* E1 — la ruta del grafo y el estado final son los esperados para cada caso.
* E2 — `retrieve` se ejecuta una sola vez y antes que `generate_answer`, que
  recibe el contexto que produjo `retrieve`.
* E3 — fuera de alcance: no se llama al LLM y la respuesta es la honesta.
* E4 — pregunta vacía: no se llega a enrutar ni a recuperar.
* E5 — **anclaje**: la respuesta usa los documentos esperados de la base de
  conocimiento del Hito 7, incluye el dato clave y no inventa cifras.
* E6 — cada transición de estado quedó guardada como checkpoint.

Parte 2 — enrutamiento entre RAG y tools:

* E7 — una pregunta por un ticket se resuelve con la tool de incidentes, **no
  con el RAG**, y la respuesta es exactamente la que sale de los datos reales.
* E8 — una pregunta de política se resuelve con el RAG, **sin ninguna tool**
  (aunque mencione una sucursal).
* E9 — una pregunta mixta usa la tool y después el RAG, en ese orden.
* E10 — fallback: ticket inexistente o servicio caído → `tool_fallback`, con
  una respuesta honesta que no afirma ningún estado.
* E11 — (extra) el stock se responde con la tool de inventario y con el número real.
* E12 — los datos de los evals son reales: el ticket y el SKU usados existen en
  la API (los devolvió la propia tool al grabar).

Servidor MCP — migración del agente:

* E13 — toda consulta a incidencias o inventario pasó por el servidor MCP
  (`transport = "mcp"` y la tool MCP usada), también en los fallbacks; el
  enrutamiento RAG / tools de E1–E12 sigue igual con el nuevo cliente MCP.
"""

import json
from pathlib import Path

import pytest

from data.pipelines import rag as rag_pipeline
from services.agent import answers, nodes

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "data" / "eval" / "agent-eval-cases.json").read_text(encoding="utf-8"))["cases"]
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "agent_traces"
TOOL_NODES = {"lookup_ticket", "lookup_inventory"}
ALL_KINDS = ("grounding", "out_of_scope", "invalid", "ticket", "rag_routing", "both", "fallback", "inventory")


def by_kind(*kinds):
    return [pytest.param(case, id=case["id"]) for case in CASES if case["kind"] in kinds]


def load_recorded_trace(case):
    path = FIXTURES_DIR / f"{case['id']}.json"
    if not path.is_file():
        pytest.fail(
            f"Falta el trace grabado {path.relative_to(ROOT)}. Grábalo con "
            "`python scripts/agent_record_traces.py` (Qdrant, .env del Hito 7 y la API en marcha)."
        )
    trace = json.loads(path.read_text(encoding="utf-8"))
    assert trace["question"] == case["question"].format(**trace.get("eval_vars", {})), "trace desactualizado: vuelve a grabarlo"
    return trace


def expected(case, trace, key):
    """Valor del caso con `{ticket_id}` / `{sku}` sustituidos por los datos reales del trace."""
    value = case[key]
    variables = trace.get("eval_vars", {})
    return [item.format(**variables) for item in value] if isinstance(value, list) else value.format(**variables)


def event(trace, node):
    return next(e for e in trace["events"] if e["node"] == node)


def retrieved_context(trace):
    return event(trace, "retrieve")["output"]["context"]


def tool_result(trace, node, key):
    return event(trace, node)["output"][key]


# --------------------------------------------------------------------------- #
# Parte 1
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", by_kind(*ALL_KINDS))
def test_e1_the_graph_takes_the_expected_route(case):
    trace = load_recorded_trace(case)
    assert trace["status"] == case["expected_status"]
    assert trace["path"] == case["expected_path"]
    assert trace["sources"] == case["expected_route"]
    assert all(e["status"] == "ok" for e in trace["events"])


@pytest.mark.parametrize("case", by_kind("grounding", "rag_routing", "both"))
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
def test_e4_empty_question_never_routes_nor_retrieves(case):
    trace = load_recorded_trace(case)
    assert "route_question" not in trace["path"] and "retrieve" not in trace["path"]
    assert trace["answer"] == nodes.INVALID_QUESTION_ANSWER


@pytest.mark.parametrize("case", by_kind("grounding", "rag_routing"))
def test_e5_answer_is_grounded_in_the_briefing_knowledge_base(case):
    trace = load_recorded_trace(case)
    context = retrieved_context(trace)
    answer = trace["answer"]

    sources = {chunk["source_document"] for chunk in context}
    assert set(case["expected_sources"]) <= sources
    for term in expected(case, trace, "answer_must_include"):
        assert term.lower() in answer.lower(), f"falta '{term}' en la respuesta"
    assert rag_pipeline.unsupported_figures(answer, context, trace["question"]) == []
    assert "Fuente:" in answer


@pytest.mark.parametrize("case", by_kind(*ALL_KINDS))
def test_e6_every_transition_was_checkpointed(case):
    trace = load_recorded_trace(case)
    steps = [checkpoint["step"] for checkpoint in trace["checkpoints"]]
    assert steps == list(range(-1, len(trace["path"]) + 1))
    assert trace["checkpoints"][-1]["next"] == []
    assert trace["checkpoints"][-1]["values"]["status"] == case["expected_status"]


# --------------------------------------------------------------------------- #
# Parte 2 — enrutamiento RAG / tools
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", by_kind("ticket"))
def test_e7_ticket_question_uses_the_tool_not_the_rag(case):
    trace = load_recorded_trace(case)
    result = tool_result(trace, "lookup_ticket", "ticket_result")

    assert trace["sources"] == ["incidents"]
    assert "retrieve" not in trace["path"] and "generate_answer" not in trace["path"]
    assert result["status"] == "ok"
    assert trace["answer"] == answers.tool_section(result)  # respuesta = datos reales, sin LLM
    for term in expected(case, trace, "answer_must_include"):
        assert term in trace["answer"]


@pytest.mark.parametrize("case", by_kind("grounding", "rag_routing", "out_of_scope"))
def test_e8_policy_question_uses_the_rag_not_a_tool(case):
    trace = load_recorded_trace(case)
    assert trace["route"]["sources"] == ["rag"]
    assert trace["sources"] == ["rag"]
    assert not TOOL_NODES & set(trace["path"])


@pytest.mark.parametrize("case", by_kind("both"))
def test_e9_mixed_question_uses_the_tool_then_the_rag(case):
    trace = load_recorded_trace(case)
    path = trace["path"]
    result = tool_result(trace, "lookup_ticket", "ticket_result")

    assert trace["sources"] == ["incidents", "rag"]
    assert path.index("lookup_ticket") < path.index("retrieve")
    assert result["status"] == "ok"
    assert trace["answer"].startswith(answers.tool_section(result))
    for term in expected(case, trace, "answer_must_include"):
        assert term.lower() in trace["answer"].lower()


@pytest.mark.parametrize("case", by_kind("fallback"))
def test_e10_tool_failure_goes_through_an_honest_fallback(case):
    trace = load_recorded_trace(case)
    result = event(trace, "tool_fallback")["output"]["ticket_result"]

    assert "tool_fallback" in trace["path"]
    assert result["status"] == case["expected_tool_status"]
    assert result["records"] == []
    assert trace["answer"] == answers.fallback_message(result)
    assert not any(label in trace["answer"] for label in answers.STATUS_LABELS.values())
    for term in expected(case, trace, "answer_must_include"):
        assert term in trace["answer"]


@pytest.mark.parametrize("case", by_kind("inventory"))
def test_e11_stock_question_uses_the_inventory_tool_with_the_real_figure(case):
    trace = load_recorded_trace(case)
    result = tool_result(trace, "lookup_inventory", "inventory_result")

    assert trace["sources"] == ["inventory"]
    assert result["status"] == "ok"
    product = result["records"][0]
    assert product["sku"] == trace["eval_vars"]["sku"]
    assert f"{product['current_stock']} unidades" in trace["answer"]
    assert trace["answer"] == answers.tool_section(result)


@pytest.mark.parametrize("case", by_kind("ticket", "both"))
def test_e12_eval_data_comes_from_the_real_api(case):
    trace = load_recorded_trace(case)
    result = tool_result(trace, "lookup_ticket", "ticket_result")
    assert result["records"][0]["id"] == trace["eval_vars"]["ticket_id"]
    assert result["query"] == {"ticket_id": int(trace["eval_vars"]["ticket_id"])}


# --------------------------------------------------------------------------- #
# Servidor MCP — el agente ya no llama al Incidents Manager directamente
# --------------------------------------------------------------------------- #
MCP_TOOL_BY_NODE = {
    "lookup_ticket": ("ticket_result", {"incidents_get", "incidents_list"}),
    "lookup_inventory": ("inventory_result", {"inventory_list_products"}),
}


@pytest.mark.parametrize("case", by_kind("ticket", "both", "fallback", "inventory"))
def test_e13_every_tool_call_went_through_the_mcp_server(case):
    trace = load_recorded_trace(case)
    used = [node for node in trace["path"] if node in MCP_TOOL_BY_NODE]
    assert used, "el caso debería usar una tool"
    for node in used:
        key, mcp_tools = MCP_TOOL_BY_NODE[node]
        result = tool_result(trace, node, key)
        assert result["transport"] == "mcp"
        assert result["mcp_tool"] in mcp_tools

