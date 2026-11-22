"""Grafo LangGraph dedicado `rfp_intake` (orchestrator-worker-synthesizer).

    START → convert_document → classify_document ─no RFP─→ discard_document → END
                                                 └RFP────→ extract_metadata → orchestrate
    orchestrate ─Send(department_worker) × departamento activo─┐   (en paralelo)
                └sin departamentos activos──────────────────────┤
    department_worker ──────────────────────────────→ synthesize → END

No comparte nodos ni estado con el grafo del agente de CX (`services/agent/graph.py`).
`RFP_GRAPH` se compila la primera vez que se pide (`get_graph()`), no al importar:
la API arranca aunque el pipeline no se use.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import nodes
from .config import GRAPH_NAME
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


def build_graph():
    builder = StateGraph(RfpState)
    builder.add_node(NODE_CONVERT, nodes.convert_document)
    builder.add_node(NODE_CLASSIFY, nodes.classify_document)
    builder.add_node(NODE_DISCARD, nodes.discard_document)
    builder.add_node(NODE_METADATA, nodes.extract_metadata)
    builder.add_node(NODE_ORCHESTRATE, nodes.orchestrate)
    builder.add_node(NODE_WORKER, nodes.department_worker)
    builder.add_node(NODE_SYNTHESIZE, nodes.synthesize)

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


@lru_cache(maxsize=1)
def get_graph():
    return build_graph()
