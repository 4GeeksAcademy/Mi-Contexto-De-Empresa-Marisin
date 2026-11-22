"""Grafo de LangGraph del agente de soporte de TrackFlow (Parte 2: RAG + tools).

    START → receive_question ─empty─→ invalid_question → END
                             └valid─→ route_question ─┬ticket────→ lookup_ticket ──┐
                                                      ├inventory─→ lookup_inventory┤ (fallo/404 → tool_fallback)
                                                      └rag───────→ retrieve ─with_context────→ generate_answer ─┐
                                                                            └without_context─→ no_context ──────┤
                                                      compose_answer ←───────────────────────────────────────────┘
                                                            ├proposal─→ propose_memory → END
                                                            └end──────→ END

Memoria (Hito 8 · Parte 1): si la conversación tiene una propuesta pendiente,
`receive_question` va primero a `resolve_memory_decision`, que clasifica el
mensaje contra ella; si queda otra consulta en el mensaje, sigue a
`route_question`, y si no, a `compose_answer`. `propose_memory` solo se ejecuta
si el modelo devolvió `memory_proposal` en este turno.

Harness (Hito 8 · Parte 2):

    receive_question ─blocked──→ guardrail_block → END     (inyección, uso personal, datos sensibles,
                     │                                      pedido de otra sesión: plantilla, sin LLM)
                     ├casual───→ redirect_out_of_scope → compose_answer   (small talk/trivia: rechazo con
                     │                                                      plantilla + reconducción, sin LLM)
                     └shipment─→ lookup_shipment → compose_answer (envíos de la sesión)
    route_question ─blocked/casual─→ guardrail_block / redirect_out_of_scope   (2.ª capa: alcance del enrutador LLM)

Las consultas de dominio permitidas siguen exactamente la ruta de la Parte 2.

`route_question` decide las fuentes (LLM + reglas). Después de cada tool,
`route_after_tool` envía a `tool_fallback` si la tool falló o el recurso no
existe, y si no, a la siguiente fuente pendiente (tools → RAG → composición).

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
NODE_INVALID = "invalid_question"
NODE_ROUTE = "route_question"
NODE_TICKET = "lookup_ticket"
NODE_INVENTORY = "lookup_inventory"
NODE_TOOL_FALLBACK = "tool_fallback"
NODE_RETRIEVE = "retrieve"
NODE_GENERATE = "generate_answer"
NODE_NO_CONTEXT = "no_context"
NODE_COMPOSE = "compose_answer"
NODE_MEMORY_DECISION = "resolve_memory_decision"
NODE_PROPOSE = "propose_memory"
NODE_BLOCK = "guardrail_block"
NODE_OUT_OF_SCOPE = "redirect_out_of_scope"
NODE_SHIPMENT = "lookup_shipment"

AGENT_SPEC = GraphSpec(
    state_schema=AgentState,
    nodes={
        NODE_RECEIVE: nodes.receive_question,
        NODE_INVALID: nodes.reject_invalid_question,
        NODE_ROUTE: nodes.route_question,
        NODE_TICKET: nodes.lookup_ticket,
        NODE_INVENTORY: nodes.lookup_inventory,
        NODE_TOOL_FALLBACK: nodes.tool_fallback,
        NODE_RETRIEVE: nodes.retrieve_context,
        NODE_GENERATE: nodes.generate_answer,
        NODE_NO_CONTEXT: nodes.answer_without_context,
        NODE_COMPOSE: nodes.compose_answer,
        NODE_MEMORY_DECISION: nodes.resolve_memory_decision,
        NODE_PROPOSE: nodes.propose_memory,
        NODE_BLOCK: nodes.guardrail_block,
        NODE_OUT_OF_SCOPE: nodes.redirect_out_of_scope,
        NODE_SHIPMENT: nodes.lookup_shipment,
    },
    edges=(
        (START, NODE_RECEIVE),
        (NODE_INVALID, END),
        (NODE_GENERATE, NODE_COMPOSE),
        (NODE_NO_CONTEXT, NODE_COMPOSE),
        (NODE_PROPOSE, END),
        (NODE_BLOCK, END),
        (NODE_OUT_OF_SCOPE, NODE_COMPOSE),
        (NODE_SHIPMENT, NODE_COMPOSE),
    ),
    conditional={
        NODE_RECEIVE: ConditionalEdge(
            router=nodes.route_after_receive,
            targets={
                "valid": NODE_ROUTE, "empty": NODE_INVALID, "memory_decision": NODE_MEMORY_DECISION,
                "blocked": NODE_BLOCK, "casual": NODE_OUT_OF_SCOPE, "shipment": NODE_SHIPMENT,
            },
        ),
        NODE_MEMORY_DECISION: ConditionalEdge(
            router=nodes.route_after_memory_decision,
            targets={"continue": NODE_ROUTE, "compose": NODE_COMPOSE},
        ),
        NODE_ROUTE: ConditionalEdge(
            router=nodes.route_after_route,
            targets={
                "ticket": NODE_TICKET, "inventory": NODE_INVENTORY, "rag": NODE_RETRIEVE, "compose": NODE_COMPOSE,
                "blocked": NODE_BLOCK, "casual": NODE_OUT_OF_SCOPE,
            },
        ),
        NODE_TICKET: ConditionalEdge(
            router=nodes.route_after_tool,
            targets={"fallback": NODE_TOOL_FALLBACK, "inventory": NODE_INVENTORY, "rag": NODE_RETRIEVE, "compose": NODE_COMPOSE},
        ),
        NODE_INVENTORY: ConditionalEdge(
            router=nodes.route_after_tool,
            targets={"fallback": NODE_TOOL_FALLBACK, "rag": NODE_RETRIEVE, "compose": NODE_COMPOSE},
        ),
        NODE_TOOL_FALLBACK: ConditionalEdge(
            router=nodes.next_source,
            targets={"inventory": NODE_INVENTORY, "rag": NODE_RETRIEVE, "compose": NODE_COMPOSE},
        ),
        NODE_RETRIEVE: ConditionalEdge(
            router=nodes.route_after_retrieve,
            targets={"with_context": NODE_GENERATE, "without_context": NODE_NO_CONTEXT},
        ),
        NODE_COMPOSE: ConditionalEdge(
            router=nodes.route_after_compose,
            targets={"propose": NODE_PROPOSE, "end": END},
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
