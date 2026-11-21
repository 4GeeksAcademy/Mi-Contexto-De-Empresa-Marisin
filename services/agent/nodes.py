"""Nodos y routers del agente de soporte. Cada nodo tiene una sola responsabilidad.

Los nodos **no reimplementan** el RAG ni las tools: llaman a
`data/pipelines/rag.py`, `services/agent/routing.py` y `services/agent/tools.py`
a través del módulo (`rag_pipeline.retrieve`, `agent_tools.lookup_tickets`, …)
para que los tests puedan sustituirlas. Ningún nodo llama a
`rag_pipeline.query()`: eso volvería a recuperar y escondería la separación
recuperación → generación que el grafo hace explícita.

Cada nodo devuelve solo las claves del estado que cambia.
"""

import logging
from typing import Literal

from data.pipelines import rag as rag_pipeline

from . import answers
from . import routing as agent_routing
from . import tools as agent_tools
from .state import AgentState

logger = logging.getLogger("agent.nodes")

INVALID_QUESTION_ANSWER = (
    "La pregunta está vacía. Escribe qué necesitas saber sobre las políticas de TrackFlow "
    "(entregas, devoluciones, transportistas o almacenaje), un ticket o el stock de un producto."
)
NO_CONTEXT_ANSWER = (
    "No tengo información sobre eso en la base de conocimiento de TrackFlow, así que prefiero "
    "no darte una respuesta que no pueda respaldar. Te recomiendo consultarlo con el responsable "
    "del área.\n"
    "Fuente: ninguna (sin información en la base de conocimiento)"
)
TOOL_RESULT_KEYS = ("ticket_result", "inventory_result")


# --------------------------------------------------------------------------- #
# Recepción y enrutamiento
# --------------------------------------------------------------------------- #
def receive_question(state: AgentState) -> AgentState:
    """Recibe y normaliza la pregunta. No recupera ni genera nada."""
    question = (state.get("question") or "").strip()
    return {"question": question, "status": "received" if question else "invalid"}


def reject_invalid_question(state: AgentState) -> AgentState:
    """Salida clara para una pregunta vacía: no se recupera nada."""
    return {"answer": INVALID_QUESTION_ANSWER, "status": "invalid"}


def route_question(state: AgentState) -> AgentState:
    """Decide qué fuentes necesita la pregunta (LLM con reglas de respaldo)."""
    decision = agent_routing.decide_route(state["question"])
    route = {**decision.model_dump(mode="json", exclude_none=True), "sources": decision.sources}
    return {"route": route, "status": "routed"}


# --------------------------------------------------------------------------- #
# Tools (datos en vivo, solo lectura)
# --------------------------------------------------------------------------- #
def lookup_ticket(state: AgentState) -> AgentState:
    """Tool 1: consulta el gestor de incidentes (GET, timeout de 4 s)."""
    query = agent_tools.TicketQuery.model_validate(state["route"]["ticket"])
    result = agent_tools.lookup_tickets(query)
    return {"ticket_result": result.model_dump(mode="json"), "status": "tool_done"}


def lookup_inventory(state: AgentState) -> AgentState:
    """Tool 2: consulta el gestor de inventario (GET, timeout de 4 s)."""
    query = agent_tools.InventoryQuery.model_validate(state["route"]["inventory"])
    result = agent_tools.lookup_inventory(query)
    return {"inventory_result": result.model_dump(mode="json"), "status": "tool_done"}


def tool_fallback(state: AgentState) -> AgentState:
    """Ruta de recuperación: la tool falló o el recurso no existe. Responde con honestidad."""
    update: AgentState = {"status": "tool_fallback"}
    for key in TOOL_RESULT_KEYS:
        result = state.get(key)
        if result and result["status"] != "ok" and not result.get("fallback_message"):
            update[key] = {**result, "fallback_message": answers.fallback_message(result)}
    return update


# --------------------------------------------------------------------------- #
# RAG
# --------------------------------------------------------------------------- #
def retrieve_context(state: AgentState) -> AgentState:
    """Ejecuta `retrieve()` del RAG; ya filtra por `min_score` y puede devolver []."""
    context = rag_pipeline.retrieve(state["question"])
    return {"context": context, "status": "retrieved"}


def generate_answer(state: AgentState) -> AgentState:
    """Genera la parte RAG con `generate_answer()` sobre el contexto YA recuperado."""
    question = state["question"]
    context = state.get("context") or []
    answer = rag_pipeline.generate_answer(question, context)
    unsupported = rag_pipeline.unsupported_figures(answer, context, question)
    if unsupported:
        logger.warning("Respuesta con cifras que no están en el contexto: %s", unsupported)
    return {"rag_answer": answer, "status": "answered"}


def answer_without_context(state: AgentState) -> AgentState:
    """Salida honesta cuando ningún chunk supera el umbral. No llama al LLM."""
    return {"rag_answer": NO_CONTEXT_ANSWER, "status": "no_context"}


# --------------------------------------------------------------------------- #
# Composición
# --------------------------------------------------------------------------- #
def compose_answer(state: AgentState) -> AgentState:
    """Une las partes en el orden de las fuentes: tools (con plantilla) y después el RAG."""
    results = [state[key] for key in TOOL_RESULT_KEYS if state.get(key)]
    sections = [answers.tool_section(result) for result in results]
    if state.get("rag_answer"):
        sections.append(state["rag_answer"])

    rag_answered = bool(state.get("context")) and bool(state.get("rag_answer"))
    if rag_answered or any(result["status"] == "ok" for result in results):
        status = "answered"
    elif results:
        status = "tool_fallback"
    else:
        status = "no_context"
    return {"answer": "\n\n".join(sections), "status": status}


# --------------------------------------------------------------------------- #
# Routers (condiciones de salida de las aristas condicionales)
# --------------------------------------------------------------------------- #
def route_after_receive(state: AgentState) -> Literal["valid", "empty"]:
    return "valid" if state.get("question") else "empty"


def next_source(state: AgentState) -> Literal["ticket", "inventory", "rag", "compose"]:
    """Siguiente fuente pendiente según la decisión del enrutador: tools → RAG → composición."""
    route = state.get("route") or {}
    if route.get("ticket") is not None and "ticket_result" not in state:
        return "ticket"
    if route.get("inventory") is not None and "inventory_result" not in state:
        return "inventory"
    if route.get("needs_rag") and "context" not in state:
        return "rag"
    return "compose"


def route_after_tool(state: AgentState) -> Literal["fallback", "inventory", "rag", "compose"]:
    """Tras una tool: si falló y aún no se ha respondido con honestidad, va a `tool_fallback`."""
    for key in TOOL_RESULT_KEYS:
        result = state.get(key)
        if result and result["status"] != "ok" and not result.get("fallback_message"):
            return "fallback"
    return next_source(state)


def route_after_retrieve(state: AgentState) -> Literal["with_context", "without_context"]:
    return "with_context" if state.get("context") else "without_context"
