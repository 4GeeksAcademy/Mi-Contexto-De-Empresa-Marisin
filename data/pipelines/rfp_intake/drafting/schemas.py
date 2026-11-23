"""Contratos de la Parte 2: entrada del generador, borrador y `EvaluationResult`.

`EvaluationResult` sigue la forma del enunciado:

    EvaluationResult:
      section_id / department_id
      readability: { pass, score, details }
      relevance:   { pass, missing_aspects[] }
      compliance:  { pass, rule_ids[], violations[] }
      overall_pass: bool
      feedback_for_generator: string

`pass` es palabra reservada en Python: el campo se llama `passed` y se
serializa como `pass` (`model_dump(by_alias=True)`, que es como se guarda en
PostgreSQL y se devuelve por la API).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..schemas import DepartmentId, Source

SectionStatus = Literal["evaluacion_superada", "needs_human_review"]


class DraftingInput(BaseModel):
    """Lo único que recibe el generador de un departamento (slice del handoff de la Parte 1)."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int | None = None
    department_id: DepartmentId
    department_name: str
    responsible: str
    client_name: str | None = None
    client_reference: str | None = None
    client_country: str | None = None
    currency: Literal["USD", "EUR"] | None = None
    services_requested: list[str] = Field(default_factory=list)
    monthly_volume: int | None = None
    deadline: str | None = None
    deadline_text: str | None = None
    budget_range: str | None = None
    ask: str = ""
    key_aspects: list[dict[str, str]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    # Tarifario de referencia del departamento en la moneda del cliente (vacío sin moneda).
    reference: str = ""
    # Fragmentos de la base de conocimiento de TrackFlow (políticas reales).
    knowledge: list[dict[str, str]] = Field(default_factory=list)


class SectionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    department_id: DepartmentId
    iteration: int = Field(ge=1)
    content: str = Field(min_length=1)
    source: Source = "rules"
    warnings: list[str] = Field(default_factory=list)


class ReadabilityCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    passed: bool = Field(alias="pass")
    score: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RelevanceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    passed: bool = Field(alias="pass")
    missing_aspects: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    detail: str
    evidence: str = ""


class ComplianceCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    passed: bool = Field(alias="pass")
    rule_ids: list[str] = Field(default_factory=list)  # reglas comprobadas
    violations: list[Violation] = Field(default_factory=list)


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    section_id: str
    department_id: DepartmentId
    iteration: int = Field(ge=1)
    readability: ReadabilityCheck
    relevance: RelevanceCheck
    compliance: ComplianceCheck
    overall_pass: bool
    feedback_for_generator: str
    evaluated_at: str


class DraftedSection(BaseModel):
    """Resultado final del ciclo de un departamento (lo que pasa a la Parte 3)."""

    model_config = ConfigDict(extra="forbid")

    department_id: DepartmentId
    department_name: str
    responsible: str
    draft_status: SectionStatus
    provisional: bool
    iterations: int
    draft_content: str
    draft_source: Source
    evaluation_result: dict[str, Any]
    evaluation_history: list[dict[str, Any]] = Field(default_factory=list)
