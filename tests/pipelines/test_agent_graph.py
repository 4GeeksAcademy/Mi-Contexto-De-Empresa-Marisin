"""Pruebas del grafo LangGraph del agente de soporte (sin Qdrant, LLM ni API en vivo).

`retrieve()` y `generate_answer()` del RAG, el enrutador LLM y la capa HTTP de
las tools se sustituyen por dobles; `query()` se sustituye por una función que
falla, para demostrar que ningún nodo usa el pipeline monolítico.

    python -m pytest tests/pipelines/test_agent_graph.py
"""

import dataclasses
import json
from typing import get_type_hints

import pytest
from langgraph.graph import END as LG_END
from langgraph.graph import START as LG_START

from data.pipelines import rag as rag_pipeline
from services.agent import graph as agent_graph
from services.agent import nodes, routing, runner, tools
from services.agent.state import AgentState
from services.agent.structure import END, START, GraphStructureError

CONTEXT = [
    {
        "company": "trackflow",
        "source_document": "returns-policy",
        "section": "Política de Devoluciones › Ventana de devolución estándar",
        "language": "es",
        "chunk_index": 1,
        "text": "Ventana de devolución estándar: 30 días desde la entrega.",
    }
]
ANSWER = "La ventana estándar es de 30 días desde la entrega.\nFuente: Política de Devoluciones"
TICKET = {
    "id": "3", "title": "Caja aplastada", "description": "d", "category": "DAMAGE", "status": "in_progress",
    "origin": "customer", "branch": "Zaragoza",
    "created_at": "2026-11-10T09:00:00+00:00", "updated_at": "2026-11-15T12:00:00+00:00",
}
PRODUCT = {"id": 1, "sku": "TF-BOX-001", "name": "Cajas de cartón XL", "client_name": "PackCo",
           "category": "embalaje", "reference": "R1", "current_stock": 120}


@pytest.fixture
def rag(monkeypatch):
    """Dobles del RAG, del LLM enrutador y de la API, que registran sus llamadas."""
    calls = {"retrieve": [], "generate": [], "http": []}
    backend = {"down": False}

    def fake_retrieve(question):
        calls["retrieve"].append(question)
        return [dict(chunk) for chunk in CONTEXT] if "devoluci" in question.lower() else []

    def fake_generate(question, context):
        calls["generate"].append((question, context))
        return ANSWER

    def fake_http(path, params=None):
        calls["http"].append(path)
        if backend["down"]:
            raise tools.ToolUnavailable("timeout: sin respuesta en 4 s")
        if path == "/api/incidents/3":
            return TICKET
        if path.startswith("/api/incidents/"):
            raise tools.ToolNotFound(path)
        if path == "/inventory/products":
            return [PRODUCT]
        raise AssertionError(path)

    def no_llm(question):
        raise RuntimeError("sin LLM en los tests")

    monkeypatch.setattr(rag_pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag_pipeline, "generate_answer", fake_generate)
    monkeypatch.setattr(rag_pipeline, "query", lambda *_: pytest.fail("ningún nodo debe llamar a query()"))
    monkeypatch.setattr(tools, "http_get_json", fake_http)
    monkeypatch.setattr(routing, "classify_with_llm", no_llm)
    calls["backend"] = backend
    return calls


@pytest.fixture
def graph():
    return agent_graph.compile_graph()  # checkpointer en memoria nuevo para cada test


def run(graph, question, thread_id="t-1"):
    config = runner.run_config(thread_id)
    return graph.invoke({"question": question}, config), config


def path_of(graph, config):
    """Nodos ejecutados, en orden, según los checkpoints."""
    history = list(reversed(list(graph.get_state_history(config))))
    return [node for snapshot in history for node in snapshot.next if node != START]


# --------------------------------------------------------------------------- #
# Estado, nodos y compilación
# --------------------------------------------------------------------------- #
def test_state_is_minimal_and_has_no_conversation_history():
    assert set(get_type_hints(AgentState)) == {
        "question", "route", "ticket_result", "inventory_result", "context", "rag_answer", "answer", "status",
    }


def test_structure_constants_are_the_langgraph_ones():
    assert (START, END) == (LG_START, LG_END)


def test_module_compiles_the_graph_with_single_responsibility_nodes():
    drawn = agent_graph.AGENT_GRAPH.get_graph()
    assert set(drawn.nodes) == {
        START, "receive_question", "invalid_question", "route_question", "lookup_ticket", "lookup_inventory",
        "tool_fallback", "retrieve", "generate_answer", "no_context", "compose_answer", END,
    }
    assert agent_graph.AGENT_GRAPH.checkpointer is not None


def test_trace_source_names_match_graph_nodes():
    assert set(runner.SOURCE_BY_NODE) <= set(agent_graph.AGENT_SPEC.nodes)


def test_edges_are_conditional_not_a_fixed_sequence():
    conditional = agent_graph.AGENT_SPEC.conditional
    assert set(conditional) == {"receive_question", "route_question", "lookup_ticket", "lookup_inventory", "tool_fallback", "retrieve"}
    assert conditional["route_question"].targets == {
        "ticket": "lookup_ticket", "inventory": "lookup_inventory", "rag": "retrieve", "compose": "compose_answer",
    }
    assert conditional["lookup_ticket"].targets["fallback"] == "tool_fallback"
    assert conditional["lookup_inventory"].targets["fallback"] == "tool_fallback"
    assert conditional["retrieve"].targets == {"with_context": "generate_answer", "without_context": "no_context"}


def test_compile_fails_clearly_on_an_unconnected_node():
    spec = dataclasses.replace(
        agent_graph.AGENT_SPEC,
        nodes={**agent_graph.AGENT_SPEC.nodes, "orphan": nodes.answer_without_context},
    )
    with pytest.raises(GraphStructureError, match="sin conexión desde START.*orphan"):
        agent_graph.compile_graph(spec)


def test_compile_fails_clearly_on_an_edge_to_an_unknown_node():
    spec = dataclasses.replace(
        agent_graph.AGENT_SPEC,
        edges=agent_graph.AGENT_SPEC.edges + (("invalid_question", "escalate_to_human"),),
    )
    with pytest.raises(GraphStructureError, match="escalate_to_human"):
        agent_graph.compile_graph(spec)


def test_compile_fails_clearly_on_a_node_that_never_reaches_end():
    spec = dataclasses.replace(
        agent_graph.AGENT_SPEC,
        edges=tuple(edge for edge in agent_graph.AGENT_SPEC.edges if edge != ("no_context", "compose_answer")),
    )
    with pytest.raises(GraphStructureError, match="no se llega a END.*no_context"):
        agent_graph.compile_graph(spec)


def test_compile_fails_clearly_on_a_badly_typed_state():
    class BrokenState:
        question: "UndefinedType"  # noqa: F821

    with pytest.raises(GraphStructureError, match="anotaciones válidas"):
        agent_graph.compile_graph(dataclasses.replace(agent_graph.AGENT_SPEC, state_schema=BrokenState))


# --------------------------------------------------------------------------- #
# Rutas
# --------------------------------------------------------------------------- #
def test_policy_question_uses_only_the_rag(graph, rag):
    final, config = run(graph, "  ¿Cuál es la ventana de devolución estándar?  ")

    assert final["status"] == "answered"
    assert final["answer"] == ANSWER
    assert final["route"]["sources"] == ["rag"]
    assert rag["retrieve"] == ["¿Cuál es la ventana de devolución estándar?"]
    assert rag["generate"] == [("¿Cuál es la ventana de devolución estándar?", CONTEXT)]
    assert rag["http"] == []  # ninguna tool
    assert path_of(graph, config) == ["receive_question", "route_question", "retrieve", "generate_answer", "compose_answer"]


def test_ticket_question_uses_the_tool_and_not_the_rag(graph, rag):
    final, config = run(graph, "¿En qué estado está el ticket 3?")

    assert final["status"] == "answered"
    assert "El ticket 3 «Caja aplastada» está en curso" in final["answer"]
    assert rag["http"] == ["/api/incidents/3"]
    assert rag["retrieve"] == [] and rag["generate"] == []
    assert path_of(graph, config) == ["receive_question", "route_question", "lookup_ticket", "compose_answer"]


def test_question_needing_both_uses_the_tool_then_the_rag(graph, rag):
    final, config = run(graph, "¿En qué estado está el ticket 3 y cuál es la ventana de devolución estándar?")

    assert final["route"]["sources"] == ["incidents", "rag"]
    assert final["answer"].index("está en curso") < final["answer"].index("30 días")
    assert path_of(graph, config) == [
        "receive_question", "route_question", "lookup_ticket", "retrieve", "generate_answer", "compose_answer",
    ]


def test_inventory_question_uses_the_inventory_tool(graph, rag):
    final, config = run(graph, "¿Tenemos stock del SKU TF-BOX-001?")

    assert "120 unidades" in final["answer"]
    assert rag["http"] == ["/inventory/products"]
    assert path_of(graph, config) == ["receive_question", "route_question", "lookup_inventory", "compose_answer"]


def test_unavailable_service_goes_through_the_fallback_without_inventing(graph, rag):
    rag["backend"]["down"] = True
    final, config = run(graph, "¿En qué estado está el ticket 3?")

    assert final["status"] == "tool_fallback"
    assert final["answer"].startswith("No he podido confirmar el estado del ticket 3")
    assert "en curso" not in final["answer"]
    assert rag["generate"] == []
    assert path_of(graph, config) == ["receive_question", "route_question", "lookup_ticket", "tool_fallback", "compose_answer"]


def test_missing_ticket_goes_through_the_fallback(graph, rag):
    final, _ = run(graph, "¿En qué estado está el ticket 999999?")
    assert final["status"] == "tool_fallback"
    assert final["ticket_result"]["status"] == "not_found"
    assert final["answer"].startswith("No encuentro el ticket 999999")


def test_the_llm_router_decides_when_it_answers(graph, rag, monkeypatch):
    decision = routing.RouteDecision(needs_rag=False, ticket=tools.TicketQuery(ticket_id=3), decided_by="llm", reason="estado")
    monkeypatch.setattr(routing, "classify_with_llm", lambda question: decision)

    final, _ = run(graph, "Necesito saber cómo va el 3 de los tickets")
    assert final["route"]["decided_by"] == "llm"
    assert rag["http"] == ["/api/incidents/3"]


def test_without_context_answers_honestly_without_calling_the_llm(graph, rag):
    final, _ = run(graph, "¿Cuál es la capital de Francia?")

    assert final["status"] == "no_context"
    assert final["answer"] == nodes.NO_CONTEXT_ANSWER
    assert len(rag["retrieve"]) == 1
    assert rag["generate"] == []


def test_empty_question_never_reaches_routing_or_retrieve(graph, rag):
    final, _ = run(graph, "   ")

    assert final["status"] == "invalid"
    assert final["answer"] == nodes.INVALID_QUESTION_ANSWER
    assert "route" not in final
    assert rag["retrieve"] == [] and rag["generate"] == [] and rag["http"] == []


# --------------------------------------------------------------------------- #
# Checkpointing
# --------------------------------------------------------------------------- #
def test_every_state_transition_is_checkpointed(graph, rag):
    _, config = run(graph, "¿Cuál es la ventana de devolución estándar?")

    history = list(reversed(list(graph.get_state_history(config))))
    assert [snapshot.metadata["step"] for snapshot in history] == [-1, 0, 1, 2, 3, 4, 5]
    assert [snapshot.next for snapshot in history] == [
        (START,),
        ("receive_question",),
        ("route_question",),
        ("retrieve",),
        ("generate_answer",),
        ("compose_answer",),
        (),
    ]
    after_retrieve = history[4]
    assert after_retrieve.values["status"] == "retrieved"
    assert after_retrieve.values["context"] == CONTEXT
    assert graph.get_state(config).values["status"] == "answered"


def test_a_run_can_be_resumed_from_a_checkpoint_without_retrieving_again(graph, rag):
    _, config = run(graph, "¿Cuál es la ventana de devolución estándar?")
    checkpoint = next(s for s in graph.get_state_history(config) if s.next == ("generate_answer",))

    resumed = graph.invoke(None, checkpoint.config)

    assert resumed["status"] == "answered"
    assert len(rag["retrieve"]) == 1  # la recuperación no se repite
    assert len(rag["generate"]) == 2  # solo se vuelve a ejecutar la generación


# --------------------------------------------------------------------------- #
# Trace
# --------------------------------------------------------------------------- #
def test_each_run_saves_a_queryable_trace_with_its_sources(graph, rag, tmp_path):
    result = runner.run_agent(
        "¿En qué estado está el ticket 3 y cuál es la ventana de devolución estándar?", graph=graph, trace_directory=tmp_path
    )

    trace = json.loads((tmp_path / f"{result.run_id}.json").read_text(encoding="utf-8"))
    assert result.trace_path == tmp_path / f"{result.run_id}.json"
    assert result.sources == ("incidents", "rag")
    assert trace["thread_id"] == result.run_id
    assert trace["status"] == "answered"
    assert trace["sources"] == ["incidents", "rag"]
    assert trace["route"]["decided_by"] == "rules"
    assert trace["path"] == [
        "receive_question", "route_question", "lookup_ticket", "retrieve", "generate_answer", "compose_answer",
    ]
    assert [event["step"] for event in trace["events"]] == [1, 2, 3, 4, 5, 6]
    assert trace["events"][2]["output"]["ticket_result"]["records"][0]["id"] == "3"
    assert trace["events"][3]["output"]["context"] == CONTEXT
    assert [checkpoint["step"] for checkpoint in trace["checkpoints"]] == [-1, 0, 1, 2, 3, 4, 5, 6]


def test_a_failing_node_is_recorded_in_the_trace_and_raises(graph, rag, monkeypatch, tmp_path):
    def broken_llm(question, context):
        raise RuntimeError("gateway LLM caído")

    monkeypatch.setattr(rag_pipeline, "generate_answer", broken_llm)

    with pytest.raises(runner.AgentRunError) as error:
        runner.run_agent("¿Cuál es la ventana de devolución estándar?", graph=graph, trace_directory=tmp_path)

    trace = json.loads((tmp_path / f"{error.value.run_id}.json").read_text(encoding="utf-8"))
    assert error.value.failed_node == "generate_answer"
    assert trace["status"] == "error"
    assert trace["failed_node"] == "generate_answer"
    assert trace["events"][-1]["error"] == {"type": "RuntimeError", "message": "gateway LLM caído"}
