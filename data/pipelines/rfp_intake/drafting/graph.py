"""Grafos LangGraph de la Parte 2: `rfp_drafting` (ticket) y `rfp_section_loop` (departamento).

    rfp_drafting:
        START → load_handoff ─Send × departamento─→ draft_department → assemble → END

    rfp_section_loop (lo ejecuta cada `draft_department`, en paralelo entre departamentos):
        START → generate ─Send─→ evaluate_readability ─┐
                         ├Send─→ evaluate_relevance ───┼→ judge ─pasa / límite─→ finalize → END
                         └Send─→ evaluate_compliance ──┘       └─falla─→ generate

Los departamentos no se bloquean entre sí: cada `draft_department` lleva su
propio ciclo completo (con su límite de iteraciones) dentro de la misma tarea
paralela, así que una sección que necesita tres rondas no hace esperar a otra
que pasó a la primera ni la arrastra a `needs_human_review`.

`build_graph(llm, reporter)` fija el LLM y el reporter en cada nodo con un
cierre (sin `config` de LangGraph). Este grafo no comparte nodos con
`rfp_intake` ni con el grafo de CX.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..llm import LLM
from . import config, nodes
from .reporter import Reporter
from .state import DraftingState, SectionState

SECTION_NODE_NAMES = (
    nodes.NODE_GENERATE, *nodes.EVALUATOR_NODES, nodes.NODE_JUDGE, nodes.NODE_FINALIZE,
)
NODE_NAMES = (nodes.NODE_LOAD, nodes.NODE_DEPARTMENT, nodes.NODE_ASSEMBLE)
# Cada iteración son 3 pasos (generar, evaluar, juzgar); margen de sobra.
SECTION_RECURSION_LIMIT = 4 * config.MAX_ITERATIONS + 10


def _bind(node, llm: LLM | None, reporter: Reporter | None):
    def run(state):
        return node(state, llm=llm, reporter=reporter)

    run.__name__ = node.__name__
    return run


def build_section_graph(llm: LLM | None = None, reporter: Reporter | None = None, checkpointer=None):
    """`checkpointer=False` cuando lo ejecuta un nodo de un grafo con checkpointer (Parte 3)."""
    builder = StateGraph(SectionState)
    builder.add_node(nodes.NODE_GENERATE, _bind(nodes.generate, llm, reporter))
    builder.add_node(nodes.NODE_READABILITY, _bind(nodes.evaluate_readability, llm, reporter))
    builder.add_node(nodes.NODE_RELEVANCE, _bind(nodes.evaluate_relevance, llm, reporter))
    builder.add_node(nodes.NODE_COMPLIANCE, _bind(nodes.evaluate_compliance, llm, reporter))
    builder.add_node(nodes.NODE_JUDGE, _bind(nodes.judge, llm, reporter))
    builder.add_node(nodes.NODE_FINALIZE, _bind(nodes.finalize, llm, reporter))

    builder.add_edge(START, nodes.NODE_GENERATE)
    builder.add_conditional_edges(nodes.NODE_GENERATE, nodes.evaluator_sends, list(nodes.EVALUATOR_NODES))
    for evaluator in nodes.EVALUATOR_NODES:
        builder.add_edge(evaluator, nodes.NODE_JUDGE)
    builder.add_conditional_edges(
        nodes.NODE_JUDGE,
        nodes.route_after_judge,
        {nodes.NODE_GENERATE: nodes.NODE_GENERATE, nodes.NODE_FINALIZE: nodes.NODE_FINALIZE},
    )
    builder.add_edge(nodes.NODE_FINALIZE, END)
    return builder.compile(checkpointer=checkpointer, name=config.SECTION_GRAPH_NAME)


def build_graph(llm: LLM | None = None, reporter: Reporter | None = None):
    section_graph = build_section_graph(llm, reporter)

    def draft_department(payload):
        result = section_graph.invoke(payload, {"recursion_limit": SECTION_RECURSION_LIMIT})
        return {"sections": [result["final"]]}

    builder = StateGraph(DraftingState)
    builder.add_node(nodes.NODE_LOAD, _bind(nodes.load_handoff, llm, reporter))
    builder.add_node(nodes.NODE_DEPARTMENT, draft_department)
    builder.add_node(nodes.NODE_ASSEMBLE, _bind(nodes.assemble, llm, reporter))

    builder.add_edge(START, nodes.NODE_LOAD)
    builder.add_conditional_edges(nodes.NODE_LOAD, nodes.department_sends, [nodes.NODE_DEPARTMENT])
    builder.add_edge(nodes.NODE_DEPARTMENT, nodes.NODE_ASSEMBLE)
    builder.add_edge(nodes.NODE_ASSEMBLE, END)
    return builder.compile(name=config.GRAPH_NAME)
