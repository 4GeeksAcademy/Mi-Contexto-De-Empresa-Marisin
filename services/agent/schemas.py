"""Contratos de `POST /agent/query` y `GET /agent/traces/{run_id}`.

`AgentQueryRequest` no exige longitud mínima a propósito: decidir qué hacer con
una pregunta vacía es responsabilidad del grafo (`invalid_question`), no del
endpoint. La respuesta nunca incluye chunks ni puntuaciones, pero sí las
fuentes usadas (`incidents`, `inventory`, `rag`); el trace completo solo lo ven
`admin` y `manager`.

Memoria (Hito 8 · Parte 1): la petición acepta `conversation_id` (si no llega, se
crea y se devuelve) y la respuesta añade `memory`: la propuesta pendiente que el
agente acaba de hacer, la decisión que se tomó sobre la anterior y cuántas
notas aprobadas se usaron. `GET /agent/memory` y `GET /agent/memory/audit`
(admin/manager) exponen la memoria consolidada y su registro de auditoría.
"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .memory.models import MemorySlot


class AgentQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(max_length=500, description="Pregunta en lenguaje natural.")
    conversation_id: UUID | None = Field(
        default=None, description="Conversación a la que pertenece el mensaje (la devuelve la primera respuesta)."
    )


class MemoryProposalView(BaseModel):
    proposal_id: str
    category: str
    fact: str
    slot_id: str
    expires_at: str
    supersedes: str | None = None


class MemoryDecisionView(BaseModel):
    proposal_id: str
    outcome: str
    label: str | None = None
    confidence: float | None = None
    decided_by: str | None = None
    fact: str | None = None
    action: str | None = None


class AgentMemoryInfo(BaseModel):
    pending_proposal: MemoryProposalView | None = Field(
        default=None, description="Propuesta que el agente acaba de hacer y espera tu sí/no."
    )
    decision: MemoryDecisionView | None = Field(default=None, description="Cómo se resolvió la propuesta anterior.")
    notes_used: int = Field(default=0, description="Notas aprobadas de la memoria usadas en la respuesta.")


class AgentQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(description="Id de la corrida; sirve para consultar su trace.")
    conversation_id: str = Field(description="Envíalo en el siguiente mensaje para seguir la conversación.")
    status: Literal["answered", "no_context", "tool_fallback", "memory_resolved"]
    answer: str
    sources: list[Literal["incidents", "inventory", "rag"]] = Field(
        description="Fuentes consultadas, en orden (tools en vivo y/o RAG)."
    )
    memory: AgentMemoryInfo


class AgentTraceEvent(BaseModel):
    step: int
    node: str
    started_at: str
    duration_ms: float
    status: Literal["ok", "error"]
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: dict[str, str] | None = None


class AgentCheckpoint(BaseModel):
    checkpoint_id: str | None = None
    step: int | None = None
    source: str | None = None
    next: list[str]
    values: dict[str, Any]


class AgentTraceResponse(BaseModel):
    run_id: str
    thread_id: str
    graph: str
    question: str
    started_at: str
    finished_at: str
    status: str
    path: list[str]
    sources: list[str] = []
    route: dict[str, Any] | None = None
    events: list[AgentTraceEvent]
    checkpoints: list[AgentCheckpoint]
    answer: str | None = None
    failed_node: str | None = None
    error: dict[str, str] | None = None
    conversation_id: str | None = None
    memory: dict[str, Any] | None = None


class AgentMemoryResponse(BaseModel):
    total_slots: int
    total_facts: int
    slots: list[MemorySlot]


class AgentMemoryAuditResponse(BaseModel):
    events: list[dict[str, Any]] = Field(description="Registro append-only, del más antiguo al más reciente.")
