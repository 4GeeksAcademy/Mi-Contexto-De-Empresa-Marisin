"""Nodos y routers del agente de soporte. Cada nodo tiene una sola responsabilidad.

Los nodos **no reimplementan** el RAG: llaman a las funciones de
`data/pipelines/rag.py` a través del módulo (`rag_pipeline.retrieve`, …) para
que los tests puedan sustituirlas. Ningún nodo llama a `rag_pipeline.query()`:
eso volvería a recuperar y escondería la separación recuperación → generación
que el grafo hace explícita.

Cada nodo devuelve solo las claves del estado que cambia.
"""

import logging
from typing import Literal

from data.pipelines import rag as rag_pipeline

from .state import AgentState

logger = logging.getLogger("agent.nodes")

INVALID_QUESTION_ANSWER = (
    "La pregunta está vacía. Escribe qué necesitas saber sobre las políticas de TrackFlow "
    "(entregas, devoluciones, transportistas o almacenaje)."
)
NO_CONTEXT_ANSWER = (
    "No tengo información sobre eso en la base de conocimiento de TrackFlow, así que prefiero "
    "no darte una respuesta que no pueda respaldar. Te recomiendo consultarlo con el responsable "
    "del área.\n"
    "Fuente: ninguna (sin información en la base de conocimiento)"
)


# --------------------------------------------------------------------------- #
# Nodos
# --------------------------------------------------------------------------- #
def receive_question(state: AgentState) -> AgentState:
    """Recibe y normaliza la pregunta. No recupera ni genera nada."""
    question = (state.get("question") or "").strip()
    return {"question": question, "status": "received" if question else "invalid"}


def retrieve_context(state: AgentState) -> AgentState:
    """Ejecuta `retrieve()` del RAG; ya filtra por `min_score` y puede devolver []."""
    context = rag_pipeline.retrieve(state["question"])
    return {"context": context, "status": "retrieved"}


def generate_answer(state: AgentState) -> AgentState:
    """Genera la respuesta con `generate_answer()` sobre el contexto YA recuperado."""
    question = state["question"]
    context = state.get("context") or []
    answer = rag_pipeline.generate_answer(question, context)
    unsupported = rag_pipeline.unsupported_figures(answer, context, question)
    if unsupported:
        logger.warning("Respuesta con cifras que no están en el contexto: %s", unsupported)
    return {"answer": answer, "status": "answered"}


def answer_without_context(state: AgentState) -> AgentState:
    """Salida honesta cuando ningún chunk supera el umbral. No llama al LLM."""
    return {"answer": NO_CONTEXT_ANSWER, "status": "no_context"}


def reject_invalid_question(state: AgentState) -> AgentState:
    """Salida clara para una pregunta vacía: no se recupera nada."""
    return {"answer": INVALID_QUESTION_ANSWER, "status": "invalid"}


# --------------------------------------------------------------------------- #
# Routers (condiciones de salida de las aristas condicionales)
# --------------------------------------------------------------------------- #
def route_after_receive(state: AgentState) -> Literal["valid", "empty"]:
    return "valid" if state.get("question") else "empty"


def route_after_retrieve(state: AgentState) -> Literal["with_context", "without_context"]:
    return "with_context" if state.get("context") else "without_context"
