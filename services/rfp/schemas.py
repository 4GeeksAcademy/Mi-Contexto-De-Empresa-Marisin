"""Contratos HTTP de la recepción de RFPs (Hito 9 · Parte 1).

Los campos con estructura propia del pipeline (clasificación, metadatos,
secciones, handoff) viajan como objetos JSON: su contrato vive en
`data/pipelines/rfp_intake/schemas.py` y en `docs/rfp-intake/rfp-intake-design.md`.
El Markdown completo no se devuelve (solo su longitud).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class RfpTicketAccepted(BaseModel):
    """Respuesta `202` del `POST`: el pipeline sigue en segundo plano."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int
    rfp_id: str
    status: str
    stage: str
    original_filename: str
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
    error_stage: str | None = None
    error_message: str | None = None
    stale: bool
    created_at: datetime
    updated_at: datetime
