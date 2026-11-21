"""Estado del grafo del agente de soporte de TrackFlow.

Mínimo y explícito: solo lo que un nodo necesita para decidir el siguiente paso.

* `question` — la pregunta normalizada (sin espacios sobrantes).
* `route` — la decisión del enrutador (`RouteDecision` serializada): qué
  fuentes hacen falta (RAG, tickets, inventario), con qué parámetros, quién lo
  decidió (`llm` o `rules`) y por qué. La leen los routers para elegir el paso
  siguiente.
* `ticket_result` / `inventory_result` — el `ToolResult` de cada tool (estado
  `ok` / `not_found` / `unavailable`, registros y error). Su presencia indica
  que la tool ya se ejecutó; su estado decide si se pasa por `tool_fallback`.
* `context` — los chunks que devolvió `retrieve()` por encima de `min_score`.
* `rag_answer` — la parte de la respuesta que redacta el RAG (o el texto
  honesto de `no_context`).
* `answer` — la respuesta final que compone `compose_answer`.
* `status` — en qué punto del flujo está la corrida; el endpoint lo devuelve.

No incluye el historial de la conversación: cada consulta es independiente y
ningún nodo lo necesita para decidir. Arrastrarlo inflaría cada checkpoint y
cada trace sin cambiar ninguna decisión.

Este módulo no usa `from __future__ import annotations` a propósito: LangGraph
lee las anotaciones del `TypedDict` para crear un canal por clave.
"""

from typing import Any, Literal, TypedDict

AgentStatus = Literal[
    "received",
    "invalid",
    "routed",
    "tool_done",
    "retrieved",
    "answered",
    "no_context",
    "tool_fallback",
]


class AgentState(TypedDict, total=False):
    question: str
    route: dict[str, Any]
    ticket_result: dict[str, Any]
    inventory_result: dict[str, Any]
    context: list[dict[str, Any]]
    rag_answer: str
    answer: str
    status: AgentStatus
