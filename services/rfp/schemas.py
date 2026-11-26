"""Contratos HTTP de la recepción de RFPs (Hito 9 · Partes 1, 2 y 3).

Los campos con estructura propia del pipeline (clasificación, metadatos,
secciones, handoff) viajan como objetos JSON: su contrato vive en
`data/pipelines/rfp_intake/schemas.py` y en `docs/rfp-intake/rfp-intake-design.md`.
El Markdown completo no se devuelve (solo su longitud).
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RfpTicketAccepted(BaseModel):
    """Respuesta `202` del `POST`: el pipeline sigue en segundo plano."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    rfp_id: str
    status: str
    stage: str
    original_filename: str
    status_url: str


class RfpDraftingAccepted(BaseModel):
    """Respuesta `202` de `POST /rfp/tickets/{id}/drafts` (Parte 2)."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    status: str
    stage: str
    status_url: str


class RfpTicketSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    rfp_id: str
    status: str
    stage: str
    original_filename: str
    client_name: str | None = None
    error_stage: str | None = None
    ready_for_drafting: bool
    ready_for_approval: bool = False
    stale: bool
    created_at: datetime
    updated_at: datetime


class RfpTicketList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tickets: list[RfpTicketSummary]


class RfpTicketDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    rfp_id: str
    status: str
    stage: str
    original_filename: str
    raw_pdf_path: str
    file_size_bytes: int
    markdown_chars: int | None = None
    classification: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    sections: list[dict[str, Any]]
    handoff: dict[str, Any] | None = None
    ready_for_drafting: bool
    # Parte 2: handoff a la Parte 3 (secciones + EvaluationResult + needs_human_review).
    drafting_handoff: dict[str, Any] | None = None
    ready_for_approval: bool = False
    # Parte 3: lo que espera cada rama interrumpida (ApprovalRequest) y si ya hay documento final.
    approval_requests: list[dict[str, Any]] = Field(default_factory=list)
    final_document_available: bool = False
    error_stage: str | None = None
    error_message: str | None = None
    stale: bool
    created_at: datetime
    updated_at: datetime


class RfpApprovalStarted(BaseModel):
    """Respuesta `202` de `POST /rfp/tickets/{id}/approvals` (Parte 3)."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    status: str
    stage: str
    status_url: str


class RfpApprovalDecisionIn(BaseModel):
    """Cuerpo de `POST /rfp/tickets/{id}/approvals/{department_id}`.

    La validación de negocio (aprobador = responsable del BRIEFING, motivo
    obligatorio para rechazar o pedir cambios) la hace `ApprovalDecision` antes
    de reanudar el grafo; aquí solo la forma.
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject", "request_changes"]
    approver: str = Field(min_length=1, max_length=120)
    comment: str = Field(default="", max_length=2000)


class RfpApprovalAccepted(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    department_id: str
    decision: str
    approval_status: str | None = None
    status: str
    stage: str
    resumed: bool  # false: la reescritura (request_changes) sigue en segundo plano
    status_url: str


class RfpTraceList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    events: list[dict[str, Any]]


class RfpFinalDocument(BaseModel):
    """FinalDocument (BRIEFING §2.3) + Markdown para Ventas."""

    model_config = ConfigDict(extra="forbid")

    contract: str
    ticket_id: int
    rfp_id: str | None = None
    client_name: str | None = None
    client_country: str | None = None
    currency: str | None = None
    sections: list[dict[str, Any]]
    arbitrations: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    delivered_to: str
    markdown: str
    generated_at: datetime
