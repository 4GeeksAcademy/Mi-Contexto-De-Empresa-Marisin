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

Memoria del agente (Hito 8 · Parte 1), solo si la corrida tiene `conversation_id`
y `actor` (las peticiones autenticadas de `POST /agent/query`):

* `conversation_id` / `run_id` / `actor` — a qué conversación pertenece la corrida,
  su id y quién pregunta (`user_id` y `role`, sin nombre ni email).
* `pending_memory` — la propuesta pendiente de esa conversación, si la había al
  empezar el turno (se clasifica antes de enrutar).
* `memory_decision` — cómo se resolvió (aprobada, rechazada, descartada, caducada).
* `memory_notes` — los hechos aprobados que se recordaron para esta pregunta.
* `memory_proposal` — qué pasó con la `memory_proposal` del modelo en este turno.

Harness (Hito 8 · Parte 2):

* `guardrail` — veredicto de la guardia de entrada (o del alcance del enrutador):
  categoría, acción (`allow`/`redirect`/`block`), tipo de fallo y reglas.
* `country_lock` — país real del pedido cuando el usuario pide aplicar la política de otro.
* `out_of_scope_reply` — plantilla para small talk/trivia (cortesía o rechazo, sin LLM), antes de la reconducción.
* `shipment_result` — envíos de la sesión que la guardia ya autorizó.

No incluye el historial de la conversación: cada consulta es independiente y
ningún nodo lo necesita para decidir. La memoria no es historial: guarda hechos
aprobados y, como mucho, una propuesta pendiente; nunca los mensajes. Arrastrarlo inflaría cada checkpoint y
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
    "memory_resolved",
    "blocked",
    "redirected",
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
    conversation_id: str
    run_id: str
    actor: dict[str, Any]
    pending_memory: dict[str, Any]
    memory_decision: dict[str, Any]
    memory_notes: list[dict[str, Any]]
    memory_proposal: dict[str, Any]
    guardrail: dict[str, Any]
    country_lock: str
    out_of_scope_reply: str
    shipment_result: list[dict[str, Any]]
