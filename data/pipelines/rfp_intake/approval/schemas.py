"""Contratos de la Parte 3: decisión humana, petición de aprobación, conflictos, arbitraje y documento final.

- `ApprovalDecision`: lo único que entra al grafo al reanudar una rama. Se valida
  **antes** de `Command(resume=…)`: decisión conocida, aprobador = responsable
  del BRIEFING para ese departamento y motivo obligatorio para rechazar o pedir
  cambios. Una respuesta inválida nunca llega al grafo (la API responde 422).
- `ApprovalRequest`: el payload de `interrupt()` — lo mínimo que necesita el
  responsable para decidir sin releer el documento (pregunta de diseño 2).
- `Conflict` / `ArbitrationDecision`: triggers del BRIEFING §7 en estado
  estructurado (pregunta de diseño 3) y su resolución con el árbitro fijo.
- `SignoffEvent`: lo que la rama de un departamento comunica al grafo del ticket
  al terminar (aprobada o rechazada).
- `FinalDocument`: entidad del BRIEFING §2.3 (`ticket_id`, `sections`, `currency`,
  `generated_at`) + el Markdown que se entrega a Ventas.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from .. import config as intake_config
from ..schemas import DepartmentId
from . import config

Decision = Literal["approve", "reject", "request_changes"]
ApprovalStatus = Literal["pendiente", "cambios_solicitados", "aprobada", "rechazada"]
Trigger = Literal["volume-vs-capacity", "returns-sla-breach", "currency-mismatch"]


class ApprovalDecision(BaseModel):
    """Respuesta humana validada. `department_id` va en el contexto de validación."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Decision
    approver: str = Field(min_length=1, max_length=120)
    comment: str = Field(default="", max_length=config.MAX_COMMENT_CHARS)

    @field_validator("approver")
    @classmethod
    def approver_is_the_named_responsible(cls, value: str, info: ValidationInfo) -> str:
        department_id = (info.context or {}).get("department_id")
        if department_id is None:
            return value
        responsible = intake_config.DEPARTMENTS[department_id].responsible
        if value != responsible:
            raise ValueError(f"solo {responsible} puede aprobar la sección de {department_id} (BRIEFING §6)")
        return value

    @model_validator(mode="after")
    def reason_is_required_to_reject_or_request_changes(self) -> "ApprovalDecision":
        if self.decision != config.DECISION_APPROVE and len(self.comment) < config.MIN_COMMENT_CHARS:
            raise ValueError(
                f"para «{self.decision}» explica el motivo (al menos {config.MIN_COMMENT_CHARS} caracteres): "
                "es el feedback que recibirá el generador"
            )
        return self


def validate_decision(payload: Any, department_id: str) -> ApprovalDecision:
    """Valida la respuesta humana para un departamento (lanza `pydantic.ValidationError`)."""
    if isinstance(payload, ApprovalDecision):
        payload = payload.model_dump()
    return ApprovalDecision.model_validate(payload, context={"department_id": department_id})


class ApprovalRequest(BaseModel):
    """Payload del `interrupt()` de una rama: lo que ve el responsable para decidir."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int | None
    department_id: DepartmentId
    department_name: str
    responsible: str
    round: int  # rondas de revisión ya hechas en la Parte 3
    max_rounds: int
    client_name: str | None = None
    currency: str | None = None
    draft_status: str | None = None
    provisional: bool = False
    iterations: int = 0
    overall_pass: bool | None = None
    violations: list[str] = Field(default_factory=list)  # rule_id de cumplimiento que fallan
    missing_aspects: list[str] = Field(default_factory=list)
    arbitration_notes: list[str] = Field(default_factory=list)  # qué decidió el árbitro sobre esta sección
    last_comment: str | None = None
    allowed_decisions: list[str] = Field(default_factory=lambda: list(config.DECISIONS))


class Conflict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: Trigger
    detail: str
    departments: list[DepartmentId]  # secciones ofensoras (las que hay que reescribir o rechazar)
    evidence: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)  # cifras estructuradas (volumen, capacidad, monedas)


class ForcedChange(BaseModel):
    """Instrucción del árbitro para una rama: se aplica como un `request_changes`."""

    model_config = ConfigDict(extra="forbid")

    trigger: Trigger
    arbiter: str
    feedback: str
    context_overrides: dict[str, Any] = Field(default_factory=dict)


class ArbitrationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trigger: Trigger
    arbiter: str
    mode: Literal["rule"] = "rule"  # regla determinista del BRIEFING; nunca un LLM votando
    rule: str
    round: int
    action: Literal["request_changes", "reject", "blocked"]
    departments: list[DepartmentId]
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)
    decided_at: str


class SignoffEvent(BaseModel):
    """Lo que una rama terminada entrega al grafo del ticket (resume de `await_signoffs`)."""

    model_config = ConfigDict(extra="forbid")

    department_id: DepartmentId
    approval_status: Literal["aprobada", "rechazada"]
    approver: str
    decided_at: str
    comment: str = ""
    reason: str = ""  # human | round-limit | arbitration-limit
    rounds: int = 0
    draft_content: str
    draft_status: str | None = None
    iterations: int = 0
    approval_requested_at: str | None = None


class FinalSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: DepartmentId
    department_name: str
    responsible: str
    approval_status: Literal["aprobada"]
    approver: str
    approved_at: str
    approval_rounds: int
    approval_minutes: float | None = None  # KPI §3: desde que la sección pidió aprobación
    draft_status: str | None = None
    content: str


class FinalDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract: str = config.DOCUMENT_CONTRACT
    ticket_id: int | None
    rfp_id: str | None = None
    client_name: str | None = None
    client_country: str | None = None
    currency: str | None
    sections: list[FinalSection]
    arbitrations: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    delivered_to: str = f"Ventas ({config.COMMERCIAL_DIRECTOR})"
    markdown: str
    generated_at: str
