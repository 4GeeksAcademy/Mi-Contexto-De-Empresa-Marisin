"""Contratos de `POST /agent/query` y `GET /agent/traces/{run_id}`.

`AgentQueryRequest` no exige longitud mínima a propósito: decidir qué hacer con
una pregunta vacía es responsabilidad del grafo (`invalid_question`), no del
endpoint. La respuesta nunca incluye chunks ni puntuaciones; el trace completo
solo lo ven `admin` y `manager`.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(max_length=500, description="Pregunta en lenguaje natural.")


class AgentQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(description="Id de la corrida; sirve para consultar su trace.")
    status: Literal["answered", "no_context"]
    answer: str


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
    events: list[AgentTraceEvent]
    checkpoints: list[AgentCheckpoint]
    answer: str | None = None
    failed_node: str | None = None
    error: dict[str, str] | None = None
