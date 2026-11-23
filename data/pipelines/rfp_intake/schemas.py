"""Contratos de datos entre los agentes del grafo `rfp_intake`.

Todo lo que produce un LLM se valida contra estos modelos antes de entrar al
estado; en el estado del grafo y en PostgreSQL viajan como `dict` (`model_dump`).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocumentType = Literal["formal_rfp", "informal_request", "vendor_pitch", "other"]
Source = Literal["llm", "rules"]
DepartmentId = Literal["warehouse", "lastmile", "reverse"]
Service = Literal["warehousing", "last_mile", "reverse_logistics"]
Country = Literal["United States", "Spain"]


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_rfp: bool
    document_type: DocumentType
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=400)
    source: Source = "llm"
    # Decisión de la otra vía (reglas si decidió el LLM y viceversa), para auditar.
    second_opinion: dict | None = None


class Contact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    role: str | None = None
    email: str | None = None


class RfpMetadata(BaseModel):
    """Metadatos de la RFP (BRIEFING §2.3). Sin cifras que no estén en el documento."""

    model_config = ConfigDict(extra="forbid")

    client_name: str | None = None
    client_reference: str | None = None
    client_country: Country | None = None
    currency: Literal["USD", "EUR"] | None = None
    services_requested: list[Service] = Field(default_factory=list)
    monthly_volume: int | None = Field(default=None, ge=0)
    deadline: date | None = None
    deadline_text: str | None = None
    budget_range: str | None = None
    contact: Contact = Field(default_factory=Contact)
    departments_needed: list[DepartmentId] = Field(default_factory=list)
    source: Source = "rules"
    # Avisos de las guardas: campos del LLM descartados por no estar anclados, etc.
    warnings: list[str] = Field(default_factory=list)


class KeyAspect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=400)
    # Cita literal del extracto que respalda el aspecto.
    evidence: str = Field(min_length=1, max_length=400)


class Workstream(BaseModel):
    """Subtarea que el orquestador asigna a un worker de departamento."""

    model_config = ConfigDict(extra="forbid")

    department_id: DepartmentId
    instructions: str
    excerpts: list[str] = Field(default_factory=list)


class DepartmentSection(BaseModel):
    """Salida de un worker (`DepartmentSection.key_aspects` del BRIEFING)."""

    model_config = ConfigDict(extra="forbid")

    department_id: DepartmentId
    department_name: str
    responsible: str
    key_aspects: list[KeyAspect] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    excerpts: list[str] = Field(default_factory=list)
    source: Source = "rules"
    warnings: list[str] = Field(default_factory=list)
