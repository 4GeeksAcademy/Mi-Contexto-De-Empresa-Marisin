"""Pruebas del grafo LangGraph del agente de soporte (sin Qdrant ni LLM en vivo).

`retrieve()` y `generate_answer()` del RAG se sustituyen por dobles; `query()`
se sustituye por una función que falla, para demostrar que ningún nodo usa el
pipeline monolítico.

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
from services.agent import nodes, runner
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


@pytest.fixture
def rag(monkeypatch):
    """Dobles del RAG que registran sus llamadas."""
    calls = {"retrieve": [], "generate": []}

    def fake_retrieve(question):
        calls["retrieve"].append(question)
        return [dict(chunk) for chunk in CONTEXT] if "devoluci" in question.lower() else []

    def fake_generate(question, context):
        calls["generate"].append((question, context))
        return ANSWER

    monkeypatch.setattr(rag_pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(rag_pipeline, "generate_answer", fake_generate)
    monkeypatch.setattr(rag_pipeline, "query", lambda *_: pytest.fail("ningún nodo debe llamar a query()"))
    return calls


@pytest.fixture
def graph():
    return agent_graph.compile_graph()  # checkpointer en memoria nuevo para cada test


def run(graph, question, thread_id="t-1"):
    config = runner.run_config(thread_id)
    return graph.invoke({"question": question}, config), config


# --------------------------------------------------------------------------- #
# Estado, nodos y compilación
# --------------------------------------------------------------------------- #
def test_state_is_minimal_and_has_no_conversation_history():
    assert set(get_type_hints(AgentState)) == {"question", "context", "answer", "status"}


def test_structure_constants_are_the_langgraph_ones():
    assert (START, END) == (LG_START, LG_END)


def test_module_compiles_the_graph_with_single_responsibility_nodes():
    drawn = agent_graph.AGENT_GRAPH.get_graph()
    assert set(drawn.nodes) == {
        START,
        "receive_question",
        "retrieve",
        "generate_answer",
        "no_context",
        "invalid_question",
        END,
    }
    assert agent_graph.AGENT_GRAPH.checkpointer is not None


def test_edges_are_conditional_not_a_fixed_sequence():
    spec = agent_graph.AGENT_SPEC
    assert set(spec.conditional) == {"receive_question", "retrieve"}
    assert spec.conditional["receive_question"].targets == {"valid": "retrieve", "empty": "invalid_question"}
    assert spec.conditional["retrieve"].targets == {"with_context": "generate_answer", "without_context": "no_context"}


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
        edges=agent_graph.AGENT_SPEC.edges + (("no_context", "escalate_to_human"),),
    )
    with pytest.raises(GraphStructureError, match="escalate_to_human"):
        agent_graph.compile_graph(spec)


def test_compile_fails_clearly_on_a_node_that_never_reaches_end():
    spec = dataclasses.replace(
        agent_graph.AGENT_SPEC,
        edges=tuple(edge for edge in agent_graph.AGENT_SPEC.edges if edge != ("no_context", END)),
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
def test_question_with_context_retrieves_once_then_generates_with_that_context(graph, rag):
    final, _ = run(graph, "  ¿Cuál es la ventana de devolución estándar?  ")

    assert final["status"] == "answered"
    assert final["answer"] == ANSWER
    assert rag["retrieve"] == ["¿Cuál es la ventana de devolución estándar?"]
    assert rag["generate"] == [("¿Cuál es la ventana de devolución estándar?", CONTEXT)]


def test_without_context_answers_honestly_without_calling_the_llm(graph, rag):
    final, _ = run(graph, "¿Cuál es la capital de Francia?")

    assert final["status"] == "no_context"
    assert final["answer"] == nodes.NO_CONTEXT_ANSWER
    assert len(rag["retrieve"]) == 1
    assert rag["generate"] == []


def test_empty_question_never_reaches_retrieve(graph, rag):
    final, _ = run(graph, "   ")

    assert final["status"] == "invalid"
    assert final["answer"] == nodes.INVALID_QUESTION_ANSWER
    assert rag["retrieve"] == [] and rag["generate"] == []


# --------------------------------------------------------------------------- #
# Checkpointing
# --------------------------------------------------------------------------- #
def test_every_state_transition_is_checkpointed(graph, rag):
    _, config = run(graph, "¿Cuál es la ventana de devolución estándar?")

    history = list(reversed(list(graph.get_state_history(config))))
    assert [snapshot.metadata["step"] for snapshot in history] == [-1, 0, 1, 2, 3]
    assert [snapshot.next for snapshot in history] == [
        (START,),
        ("receive_question",),
        ("retrieve",),
        ("generate_answer",),
        (),
    ]
    after_retrieve = history[3]
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
def test_each_run_saves_a_queryable_trace(graph, rag, tmp_path):
    result = runner.run_agent("¿Cuál es la ventana de devolución estándar?", graph=graph, trace_directory=tmp_path)

    trace = json.loads((tmp_path / f"{result.run_id}.json").read_text(encoding="utf-8"))
    assert result.trace_path == tmp_path / f"{result.run_id}.json"
    assert trace["thread_id"] == result.run_id
    assert trace["status"] == "answered"
    assert trace["path"] == ["receive_question", "retrieve", "generate_answer"]
    assert [event["step"] for event in trace["events"]] == [1, 2, 3]
    assert trace["events"][1]["output"]["context"] == CONTEXT
    assert trace["events"][2]["output"]["answer"] == ANSWER
    assert [checkpoint["step"] for checkpoint in trace["checkpoints"]] == [-1, 0, 1, 2, 3]


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
