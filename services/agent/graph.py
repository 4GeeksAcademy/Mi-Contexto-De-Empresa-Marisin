"""Grafo de LangGraph del agente de soporte de TrackFlow.

    START → receive_question ─valid──→ retrieve ─with_context────→ generate_answer → END
                             └empty──→ invalid_question → END
                                                 └without_context─→ no_context → END

El grafo se declara como datos (`AGENT_SPEC`), se valida con
`validate_structure()` y se compila con `compile_graph()`. `AGENT_GRAPH` se
compila al importar este módulo, es decir, al arrancar la API: un error
estructural impide arrancar en vez de aparecer en una petición.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph

from . import nodes
from .state import AgentState
from .structure import END, START, ConditionalEdge, GraphSpec, GraphStructureError, validate_structure
from .tracing import traced

GRAPH_NAME = "trackflow_support_agent"

NODE_RECEIVE = "receive_question"
NODE_RETRIEVE = "retrieve"
NODE_GENERATE = "generate_answer"
NODE_NO_CONTEXT = "no_context"
NODE_INVALID = "invalid_question"

AGENT_SPEC = GraphSpec(
    state_schema=AgentState,
    nodes={
        NODE_RECEIVE: nodes.receive_question,
        NODE_RETRIEVE: nodes.retrieve_context,
        NODE_GENERATE: nodes.generate_answer,
        NODE_NO_CONTEXT: nodes.answer_without_context,
        NODE_INVALID: nodes.reject_invalid_question,
    },
    edges=(
        (START, NODE_RECEIVE),
        (NODE_GENERATE, END),
        (NODE_NO_CONTEXT, END),
        (NODE_INVALID, END),
    ),
    conditional={
        NODE_RECEIVE: ConditionalEdge(
            router=nodes.route_after_receive,
            targets={"valid": NODE_RETRIEVE, "empty": NODE_INVALID},
        ),
        NODE_RETRIEVE: ConditionalEdge(
            router=nodes.route_after_retrieve,
            targets={"with_context": NODE_GENERATE, "without_context": NODE_NO_CONTEXT},
        ),
    },
)


def compile_graph(spec: GraphSpec = AGENT_SPEC, *, checkpointer: Any = None):
    """Valida y compila el grafo. Lanza `GraphStructureError` si está mal formado.

    Sin `checkpointer` usa un `InMemorySaver` propio: cada transición de estado
    queda guardada como checkpoint del hilo `thread_id` de la corrida.
    """
    validate_structure(spec)
    try:
        builder = StateGraph(spec.state_schema)
        for name, action in spec.nodes.items():
            builder.add_node(name, traced(name, action))
        for source, target in spec.edges:
            builder.add_edge(source, target)
        for source, edge in spec.conditional.items():
            builder.add_conditional_edges(source, edge.router, edge.targets)
        return builder.compile(
            checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
            name=GRAPH_NAME,
        )
    except GraphStructureError:
        raise
    except (ValueError, TypeError) as exc:
        raise GraphStructureError(f"LangGraph rechazó el grafo al compilar: {exc}") from exc


AGENT_GRAPH = compile_graph()
