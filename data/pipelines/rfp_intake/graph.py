"""Grafo LangGraph dedicado `rfp_intake` (orchestrator-worker-synthesizer).

    START → convert_document → classify_document ─no RFP─→ discard_document → END
                                                 └RFP────→ extract_metadata → orchestrate
    orchestrate ─Send(department_worker) × departamento activo─┐   (en paralelo)
                └sin departamentos activos──────────────────────┤
    department_worker ──────────────────────────────→ synthesize → END

No comparte nodos ni estado con el grafo del agente de CX (`services/agent/graph.py`).
`build_graph(llm)` fija el LLM en cada nodo con un cierre de un solo argumento
(sin `config`); el runner compila un grafo por ejecución, que es barato.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import nodes
from .config import GRAPH_NAME
from .llm import LLM
from .state import RfpState

NODE_CONVERT = "convert_document"
NODE_CLASSIFY = "classify_document"
NODE_DISCARD = "discard_document"
NODE_METADATA = "extract_metadata"
NODE_ORCHESTRATE = "orchestrate"
NODE_WORKER = "department_worker"
NODE_SYNTHESIZE = "synthesize"

NODE_NAMES = (
    NODE_CONVERT, NODE_CLASSIFY, NODE_DISCARD, NODE_METADATA, NODE_ORCHESTRATE, NODE_WORKER, NODE_SYNTHESIZE,
)


def fan_out(state: RfpState) -> list[Send] | str:
    """Un `Send` por departamento activo; sin departamentos, directo al synthesizer."""
    inputs = nodes.worker_inputs(state)
    if not inputs:
        return NODE_SYNTHESIZE
    return [Send(NODE_WORKER, worker_input) for worker_input in inputs]


def _bind(node, llm: LLM | None):
    def run(state):
        return node(state, llm=llm)

    run.__name__ = node.__name__
    return run


def build_graph(llm: LLM | None = None):
    builder = StateGraph(RfpState)
    builder.add_node(NODE_CONVERT, _bind(nodes.convert_document, llm))
    builder.add_node(NODE_CLASSIFY, _bind(nodes.classify_document, llm))
    builder.add_node(NODE_DISCARD, _bind(nodes.discard_document, llm))
    builder.add_node(NODE_METADATA, _bind(nodes.extract_metadata, llm))
    builder.add_node(NODE_ORCHESTRATE, _bind(nodes.orchestrate, llm))
    builder.add_node(NODE_WORKER, _bind(nodes.department_worker, llm))
    builder.add_node(NODE_SYNTHESIZE, _bind(nodes.synthesize, llm))

    builder.add_edge(START, NODE_CONVERT)
    builder.add_edge(NODE_CONVERT, NODE_CLASSIFY)
    builder.add_conditional_edges(
        NODE_CLASSIFY,
        nodes.route_after_classification,
        {NODE_METADATA: NODE_METADATA, NODE_DISCARD: NODE_DISCARD},
    )
    builder.add_edge(NODE_DISCARD, END)
    builder.add_edge(NODE_METADATA, NODE_ORCHESTRATE)
    builder.add_conditional_edges(NODE_ORCHESTRATE, fan_out, [NODE_WORKER, NODE_SYNTHESIZE])
    builder.add_edge(NODE_WORKER, NODE_SYNTHESIZE)
    builder.add_edge(NODE_SYNTHESIZE, END)
    return builder.compile(name=GRAPH_NAME)
