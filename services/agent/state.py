"""Estado del grafo del agente de soporte de TrackFlow.

Mínimo y explícito: solo lo que un nodo necesita para decidir el siguiente paso.

* `question` — la pregunta normalizada (sin espacios sobrantes).
* `context` — los chunks que devolvió `retrieve()` por encima de `min_score`
  (payloads de Qdrant: `source_document`, `section`, `text`…).
* `answer` — la respuesta final (del modelo o de un nodo de salida fijo).
* `status` — en qué punto del flujo está la corrida; es lo que leen los
  routers y lo que el endpoint devuelve al cliente.

No incluye el historial de la conversación: cada consulta es independiente y
ningún nodo lo necesita para decidir. Arrastrarlo inflaría cada checkpoint y
cada trace sin cambiar ninguna decisión. Si la memoria conversacional llega
(Hito 8), se añadirá con su propia justificación.

Este módulo no usa `from __future__ import annotations` a propósito: LangGraph
lee las anotaciones del `TypedDict` para crear un canal por clave.
"""

from typing import Any, Literal, TypedDict

AgentStatus = Literal["received", "invalid", "retrieved", "answered", "no_context"]


class AgentState(TypedDict, total=False):
    question: str
    context: list[dict[str, Any]]
    answer: str
    status: AgentStatus
