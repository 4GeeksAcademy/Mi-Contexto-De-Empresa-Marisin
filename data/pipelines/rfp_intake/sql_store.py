"""Persistencia del ticket RFP en PostgreSQL (Supabase) con SQLModel.

Tres tablas en `public` (DDL idempotente con checks, índices y RLS en
`services/sql/003_rfp_intake.sql`; `SQLModel.metadata.create_all` al arrancar la
API también las crea si faltan, sin los checks):

- `rfp_tickets`: el ticket y su ciclo de vida (`status`, `stage`, PDF en
  `data/raw/rfp/`, Markdown convertido —la Parte 2 no vuelve a leer el PDF—,
  clasificación, error, handoff y la bandera `ready_for_drafting` que lee la Parte 2).
- `rfp_metadata`: metadatos de la RFP (BRIEFING §2.3) y métricas de legibilidad.
- `rfp_department_sections`: una fila por departamento activo con `key_aspects`;
  la Parte 2 rellena `draft_content`, `evaluation_results` (último
  `EvaluationResult`), `draft_status`, `iterations`, `evaluation_history` y
  `draft_source`; `approval_status`, `approver` y `approved_at` son de la Parte 3.

Parte 2 (`services/sql/004_rfp_drafting.sql`): `rfp_tickets.drafting_handoff`
(contrato `trackflow.rfp_drafting.handoff/v1`) y la bandera `ready_for_approval`.

Parte 3 (`services/sql/005_rfp_approval.sql`): en cada sección `approval_round`,
`approval_comment`, `approval_requested_at` y `approval_history` (además de
`approval_status`, `approver` y `approved_at` del BRIEFING); `rfp_final_documents`
(FinalDocument) y `rfp_trace_events` (traza de cada nodo: agente, input, output, hora).

Las horas se calculan en Python (UTC), como en `services/job_runner.py`, para que
el mismo código funcione en Supabase y en el SQLite en memoria de los tests.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import JSON, Column, DateTime, Text, UniqueConstraint, delete
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, select

from . import config
from .approval import config as approval_config
from .drafting import config as drafting_config
from .store import (
    SECTION_APPROVAL_DEFAULTS, SECTION_DRAFT_DEFAULTS, NotApprovable, NotDraftable, TicketNotFound,
    approval_refusal, drafting_refusal, utc_now,
)


class RfpTicket(SQLModel, table=True):
    __tablename__ = "rfp_tickets"

    ticket_id: Optional[int] = Field(default=None, primary_key=True)
    rfp_id: str = Field(index=True, unique=True)
    status: str = Field(default=config.STATUS_ANALYZING, index=True)
    stage: str = Field(default=config.STAGE_RECEIVED)
    raw_pdf_path: str
    original_filename: str
    file_sha256: str = Field(index=True)
    file_size_bytes: int
    uploaded_by: Optional[str] = None
    markdown_chars: Optional[int] = None
    # Markdown convertido (también de los descartados: permite auditar falsos negativos).
    markdown: Optional[str] = Field(default=None, sa_column=Column(Text))
    classification: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    error_stage: Optional[str] = None
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    handoff: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    ready_for_drafting: bool = Field(default=False, index=True)
    # Parte 2: handoff a la Parte 3 y su bandera de cola.
    drafting_handoff: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    ready_for_approval: bool = Field(default=False)
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class RfpMetadataRow(SQLModel, table=True):
    __tablename__ = "rfp_metadata"

    ticket_id: int = Field(foreign_key="rfp_tickets.ticket_id", primary_key=True)
    client_name: Optional[str] = None
    client_reference: Optional[str] = None
    client_country: Optional[str] = None
    currency: Optional[str] = None
    services_requested: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    monthly_volume: Optional[int] = None
    deadline: Optional[date] = None
    deadline_text: Optional[str] = None
    budget_range: Optional[str] = None
    contact: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    departments_needed: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    readability: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    word_count: Optional[int] = None
    estimated_tokens: Optional[int] = None
    extraction_source: str = "rules"
    warnings: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class RfpDepartmentSectionRow(SQLModel, table=True):
    __tablename__ = "rfp_department_sections"
    __table_args__ = (UniqueConstraint("ticket_id", "department_id", name="rfp_department_sections_ticket_dept_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.ticket_id", index=True)
    department_id: str
    department_name: str
    responsible: str
    key_aspects: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    open_questions: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    excerpts: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    source: str = "rules"
    warnings: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # Partes 2 y 3 (BRIEFING §2.3): vacíos en la Parte 1.
    draft_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    evaluation_results: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    # Parte 2: estado de la sección en el ciclo generador-evaluador.
    draft_status: Optional[str] = None
    iterations: int = Field(default=0)
    evaluation_history: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    draft_source: Optional[str] = None
    approval_status: Optional[str] = None
    approver: Optional[str] = None
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    # Parte 3: rondas de revisión, último comentario, cuándo pidió aprobación (KPI) e historial de decisiones.
    approval_round: int = Field(default=0)
    approval_comment: Optional[str] = Field(default=None, sa_column=Column(Text))
    approval_requested_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    approval_history: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class RfpFinalDocumentRow(SQLModel, table=True):
    """FinalDocument (BRIEFING §2.3): ticket_id, sections, currency, generated_at (+ Markdown para Ventas)."""

    __tablename__ = "rfp_final_documents"

    ticket_id: int = Field(foreign_key="rfp_tickets.ticket_id", primary_key=True)
    contract: str = approval_config.DOCUMENT_CONTRACT
    client_name: Optional[str] = None
    currency: Optional[str] = None
    sections: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    arbitrations: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    metrics: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    markdown: str = Field(sa_column=Column(Text, nullable=False))
    delivered_to: str
    generated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))


class RfpTraceEventRow(SQLModel, table=True):
    """Una ejecución de nodo de cualquiera de las tres partes, en orden (`id`)."""

    __tablename__ = "rfp_trace_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    ticket_id: int = Field(foreign_key="rfp_tickets.ticket_id", index=True)
    graph: str
    thread_id: Optional[str] = None
    department_id: Optional[str] = None
    node: str
    agent: str
    status: str = "ok"
    input: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    output: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    started_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    finished_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    duration_ms: Optional[int] = None


RFP_TABLES = [
    RfpTicket.__table__, RfpMetadataRow.__table__, RfpDepartmentSectionRow.__table__,
    RfpFinalDocumentRow.__table__, RfpTraceEventRow.__table__,
]

_METADATA_FIELDS = (
    "client_name", "client_reference", "client_country", "currency", "services_requested", "monthly_volume",
    "deadline_text", "budget_range", "contact", "departments_needed", "warnings",
)
_SECTION_FIELDS = (
    "department_id", "department_name", "responsible", "key_aspects", "open_questions", "excerpts", "source",
    "warnings", "draft_content", "evaluation_results", "draft_status", "iterations", "evaluation_history",
    "draft_source", "approval_status", "approver", "approved_at", "approval_round", "approval_comment",
    "approval_requested_at", "approval_history",
)


def _ticket_dict(row: RfpTicket) -> dict[str, Any]:
    return row.model_dump(exclude={"markdown"})


def _metadata_dict(row: RfpMetadataRow) -> dict[str, Any]:
    data = {field: getattr(row, field) for field in _METADATA_FIELDS}
    data["deadline"] = row.deadline.isoformat() if row.deadline else None
    data["source"] = row.extraction_source
    data["readability"] = row.readability
    return data


def _section_dict(row: RfpDepartmentSectionRow) -> dict[str, Any]:
    return {field: getattr(row, field) for field in _SECTION_FIELDS}


def _as_datetime(value: Any) -> Any:
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


_TRACE_FIELDS = ("graph", "thread_id", "department_id", "node", "agent", "status", "input", "output", "duration_ms")


def _trace_dict(row: RfpTraceEventRow) -> dict[str, Any]:
    data = {field: getattr(row, field) for field in _TRACE_FIELDS}
    return {"id": row.id, "ticket_id": row.ticket_id, **data,
            "started_at": _iso(row.started_at), "finished_at": _iso(row.finished_at)}


class SqlRfpStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _get(self, session: Session, ticket_id: int) -> RfpTicket:
        row = session.get(RfpTicket, ticket_id)
        if row is None:
            raise TicketNotFound(ticket_id)
        return row

    def _update(self, ticket_id: int, **changes: Any) -> None:
        with Session(self.engine) as session:
            row = self._get(session, ticket_id)
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_at = utc_now()
            session.add(row)
            session.commit()

    def create_ticket(self, *, rfp_id, raw_pdf_path, original_filename, file_sha256, file_size_bytes, uploaded_by):
        with Session(self.engine) as session:
            row = RfpTicket(
                rfp_id=rfp_id, raw_pdf_path=raw_pdf_path, original_filename=original_filename,
                file_sha256=file_sha256, file_size_bytes=file_size_bytes, uploaded_by=uploaded_by,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _ticket_dict(row)

    def get_ticket(self, ticket_id):
        with Session(self.engine) as session:
            row = session.get(RfpTicket, ticket_id)
            if row is None:
                return None
            ticket = _ticket_dict(row)
            metadata = session.get(RfpMetadataRow, ticket_id)
            ticket["metadata"] = _metadata_dict(metadata) if metadata else None
            sections = session.exec(
                select(RfpDepartmentSectionRow).where(RfpDepartmentSectionRow.ticket_id == ticket_id)
            ).all()
            ordered = sorted(sections, key=lambda s: config.DEPARTMENT_ORDER.index(s.department_id))
            ticket["sections"] = [_section_dict(section) for section in ordered]
            return ticket

    def list_tickets(self, limit=50):
        with Session(self.engine) as session:
            rows = session.exec(
                select(RfpTicket, RfpMetadataRow.client_name)
                .join(RfpMetadataRow, RfpMetadataRow.ticket_id == RfpTicket.ticket_id, isouter=True)
                .order_by(RfpTicket.ticket_id.desc())
                .limit(limit)
            ).all()
            return [{**_ticket_dict(ticket), "client_name": client_name} for ticket, client_name in rows]

    def start_processing(self, ticket_id):
        with Session(self.engine) as session:
            row = self._get(session, ticket_id)
            session.execute(delete(RfpFinalDocumentRow).where(RfpFinalDocumentRow.ticket_id == ticket_id))
            session.execute(delete(RfpDepartmentSectionRow).where(RfpDepartmentSectionRow.ticket_id == ticket_id))
            session.execute(delete(RfpMetadataRow).where(RfpMetadataRow.ticket_id == ticket_id))
            row.status = config.STATUS_ANALYZING
            row.stage = config.STAGE_CONVERTING
            row.classification = None
            row.error_stage = None
            row.error_message = None
            row.handoff = None
            row.ready_for_drafting = False
            row.drafting_handoff = None
            row.ready_for_approval = False
            row.updated_at = utc_now()
            session.add(row)
            session.commit()

    def set_stage(self, ticket_id, stage):
        self._update(ticket_id, stage=stage)

    def save_markdown(self, ticket_id, markdown):
        self._update(ticket_id, markdown=markdown, markdown_chars=len(markdown))

    def get_markdown(self, ticket_id):
        with Session(self.engine) as session:
            row = session.get(RfpTicket, ticket_id)
            return row.markdown if row is not None else None

    def save_classification(self, ticket_id, classification, stage):
        self._update(ticket_id, classification=classification, stage=stage)

    def discard(self, ticket_id):
        self._update(ticket_id, status=config.STATUS_DISCARDED, stage=config.STAGE_DISCARDED)

    def save_metadata(self, ticket_id, metadata, readability):
        with Session(self.engine) as session:
            ticket = self._get(session, ticket_id)
            deadline = metadata.get("deadline")
            row = RfpMetadataRow(
                ticket_id=ticket_id,
                **{field: metadata.get(field) for field in _METADATA_FIELDS if field not in ("contact",)},
                contact=metadata.get("contact") or {},
                deadline=date.fromisoformat(deadline) if isinstance(deadline, str) else deadline,
                readability=readability or {},
                word_count=(readability or {}).get("word_count"),
                estimated_tokens=(readability or {}).get("estimated_tokens"),
                extraction_source=metadata.get("source") or "rules",
            )
            for field in ("services_requested", "departments_needed", "warnings"):
                if getattr(row, field) is None:
                    setattr(row, field, [])
            session.merge(row)
            ticket.stage = config.STAGE_ORCHESTRATING
            ticket.updated_at = utc_now()
            session.add(ticket)
            session.commit()

    def save_section(self, ticket_id, section):
        with Session(self.engine) as session:
            ticket = self._get(session, ticket_id)
            existing = session.exec(
                select(RfpDepartmentSectionRow).where(
                    RfpDepartmentSectionRow.ticket_id == ticket_id,
                    RfpDepartmentSectionRow.department_id == section["department_id"],
                )
            ).first()
            row = existing or RfpDepartmentSectionRow(
                ticket_id=ticket_id,
                department_id=section["department_id"],
                department_name=section["department_name"],
                responsible=section["responsible"],
            )
            for field in ("department_name", "responsible", "key_aspects", "open_questions", "excerpts", "source", "warnings"):
                setattr(row, field, section.get(field) if section.get(field) is not None else getattr(row, field))
            session.add(row)
            ticket.stage = config.STAGE_DEPARTMENTS
            ticket.updated_at = utc_now()
            session.add(ticket)
            session.commit()

    def complete(self, ticket_id, handoff):
        self._update(
            ticket_id,
            status=config.STATUS_ANALYSIS_COMPLETE,
            stage=config.STAGE_DONE,
            handoff=handoff,
            ready_for_drafting=bool(handoff.get("ready_for_drafting")),
        )

    def fail(self, ticket_id, stage, message):
        try:
            self._update(ticket_id, stage=config.STAGE_ERROR, error_stage=stage, error_message=message[:2000])
        except TicketNotFound:
            pass

    # ------------------------------------------------------------------ #
    # Parte 2 · generación y evaluación de borradores
    # ------------------------------------------------------------------ #
    def list_ready_for_drafting(self, limit=50):
        """La cola de la Parte 2 (índice parcial `rfp_tickets_ready_for_drafting_idx`)."""
        with Session(self.engine) as session:
            rows = session.exec(
                select(RfpTicket)
                .where(RfpTicket.ready_for_drafting, RfpTicket.status == config.STATUS_ANALYSIS_COMPLETE)
                .order_by(RfpTicket.ticket_id)
                .limit(limit)
            ).all()
            return [_ticket_dict(row) for row in rows]

    def claim_for_drafting(self, ticket_id, *, force=False):
        """Toma el ticket de la cola de forma atómica (`SELECT … FOR UPDATE` en PostgreSQL)."""
        with Session(self.engine) as session:
            row = session.exec(select(RfpTicket).where(RfpTicket.ticket_id == ticket_id).with_for_update()).first()
            if row is None:
                raise TicketNotFound(ticket_id)
            reason = drafting_refusal(_ticket_dict(row), force=force)
            if reason:
                raise NotDraftable(reason)
            row.status = drafting_config.STATUS_GENERATING
            row.stage = drafting_config.STAGE_GENERATING
            row.ready_for_drafting = False
            row.drafting_handoff = None
            row.ready_for_approval = False
            row.error_stage = None
            row.error_message = None
            row.updated_at = utc_now()
            session.add(row)
            for section in session.exec(
                select(RfpDepartmentSectionRow).where(RfpDepartmentSectionRow.ticket_id == ticket_id)
            ).all():
                for field, value in {**SECTION_DRAFT_DEFAULTS, **SECTION_APPROVAL_DEFAULTS}.items():
                    setattr(section, field, list(value) if isinstance(value, list) else value)
                session.add(section)
            session.execute(delete(RfpFinalDocumentRow).where(RfpFinalDocumentRow.ticket_id == ticket_id))
            session.commit()
            session.refresh(row)
            return _ticket_dict(row)

    def set_drafting_progress(self, ticket_id, status, stage):
        self._update(ticket_id, status=status, stage=stage)

    def save_section_draft(self, ticket_id, department_id, **changes):
        entry = changes.pop("history_entry", None)
        with Session(self.engine) as session:
            ticket = self._get(session, ticket_id)
            section = session.exec(
                select(RfpDepartmentSectionRow).where(
                    RfpDepartmentSectionRow.ticket_id == ticket_id,
                    RfpDepartmentSectionRow.department_id == department_id,
                )
            ).first()
            if section is None:
                raise KeyError(f"El ticket {ticket_id} no tiene sección {department_id}")
            for field, value in changes.items():
                setattr(section, field, value)
            if entry is not None:
                # Lista nueva: SQLAlchemy no detecta cambios dentro de una columna JSON mutada en sitio.
                section.evaluation_history = [*(section.evaluation_history or []), entry]
            session.add(section)
            ticket.updated_at = utc_now()
            session.add(ticket)
            session.commit()

    def complete_drafting(self, ticket_id, output):
        self._update(
            ticket_id,
            status=output["status"],
            stage=drafting_config.STAGE_DRAFTS_READY,
            drafting_handoff=output,
            ready_for_approval=bool(output.get("ready_for_approval")),
        )

    # ------------------------------------------------------------------ #
    # Parte 3 · aprobación humana, arbitraje y documento final
    # ------------------------------------------------------------------ #
    def list_ready_for_approval(self, limit=50):
        """La cola de la Parte 3 (índice parcial `rfp_tickets_ready_for_approval_idx`)."""
        with Session(self.engine) as session:
            rows = session.exec(
                select(RfpTicket)
                .where(
                    RfpTicket.ready_for_approval,
                    RfpTicket.status.in_(approval_config.APPROVABLE_STATUSES),
                    RfpTicket.stage == drafting_config.STAGE_DRAFTS_READY,
                )
                .order_by(RfpTicket.ticket_id)
                .limit(limit)
            ).all()
            return [_ticket_dict(row) for row in rows]

    def claim_for_approval(self, ticket_id, *, force=False):
        """Toma el ticket de la cola de la Parte 3 de forma atómica (`SELECT … FOR UPDATE`)."""
        with Session(self.engine) as session:
            row = session.exec(select(RfpTicket).where(RfpTicket.ticket_id == ticket_id).with_for_update()).first()
            if row is None:
                raise TicketNotFound(ticket_id)
            reason = approval_refusal(_ticket_dict(row), force=force)
            if reason:
                raise NotApprovable(reason)
            row.status = approval_config.STATUS_AWAITING
            row.stage = approval_config.STAGE_AWAITING
            row.ready_for_approval = False
            row.error_stage = None
            row.error_message = None
            row.updated_at = utc_now()
            session.add(row)
            for section in session.exec(
                select(RfpDepartmentSectionRow).where(RfpDepartmentSectionRow.ticket_id == ticket_id)
            ).all():
                for field, value in SECTION_APPROVAL_DEFAULTS.items():
                    setattr(section, field, list(value) if isinstance(value, list) else value)
                session.add(section)
            session.execute(delete(RfpFinalDocumentRow).where(RfpFinalDocumentRow.ticket_id == ticket_id))
            session.commit()
            session.refresh(row)
            return _ticket_dict(row)

    def set_approval_progress(self, ticket_id, stage, status=approval_config.STATUS_AWAITING):
        self._update(ticket_id, status=status, stage=stage)

    def save_section_approval(self, ticket_id, department_id, **changes):
        entry = changes.pop("decision_entry", None)
        with Session(self.engine) as session:
            ticket = self._get(session, ticket_id)
            section = session.exec(
                select(RfpDepartmentSectionRow).where(
                    RfpDepartmentSectionRow.ticket_id == ticket_id,
                    RfpDepartmentSectionRow.department_id == department_id,
                )
            ).first()
            if section is None:
                raise KeyError(f"El ticket {ticket_id} no tiene sección {department_id}")
            for field, value in changes.items():
                if field in ("approved_at", "approval_requested_at"):
                    value = _as_datetime(value)
                setattr(section, field, value)
            if entry is not None:
                section.approval_history = [*(section.approval_history or []), entry]
            session.add(section)
            ticket.updated_at = utc_now()
            session.add(ticket)
            session.commit()

    def save_final_document(self, ticket_id, document):
        with Session(self.engine) as session:
            ticket = self._get(session, ticket_id)
            session.merge(
                RfpFinalDocumentRow(
                    ticket_id=ticket_id,
                    contract=document.get("contract") or approval_config.DOCUMENT_CONTRACT,
                    client_name=document.get("client_name"),
                    currency=document.get("currency"),
                    sections=document.get("sections") or [],
                    arbitrations=document.get("arbitrations") or [],
                    metrics=document.get("metrics") or {},
                    markdown=document["markdown"],
                    delivered_to=document.get("delivered_to") or "",
                    generated_at=_as_datetime(document["generated_at"]),
                )
            )
            ticket.status = approval_config.STATUS_DONE
            ticket.stage = approval_config.STAGE_DONE
            ticket.updated_at = utc_now()
            session.add(ticket)
            session.commit()

    def get_final_document(self, ticket_id):
        with Session(self.engine) as session:
            row = session.get(RfpFinalDocumentRow, ticket_id)
            if row is None:
                return None
            ticket = session.get(RfpTicket, ticket_id)
            return {
                "contract": row.contract, "ticket_id": row.ticket_id, "rfp_id": ticket.rfp_id if ticket else None,
                "client_name": row.client_name, "currency": row.currency, "sections": row.sections,
                "arbitrations": row.arbitrations, "metrics": row.metrics, "markdown": row.markdown,
                "delivered_to": row.delivered_to, "generated_at": _iso(row.generated_at),
            }

    def append_trace(self, ticket_id, entry):
        with Session(self.engine) as session:
            session.add(
                RfpTraceEventRow(
                    ticket_id=ticket_id,
                    **{field: entry.get(field) for field in _TRACE_FIELDS if field not in ("input", "output")},
                    input=entry.get("input") or {},
                    output=entry.get("output") or {},
                    started_at=_as_datetime(entry.get("started_at")),
                    finished_at=_as_datetime(entry.get("finished_at")) or utc_now(),
                )
            )
            session.commit()

    def list_trace(self, ticket_id, limit=2000):
        with Session(self.engine) as session:
            rows = session.exec(
                select(RfpTraceEventRow).where(RfpTraceEventRow.ticket_id == ticket_id)
                .order_by(RfpTraceEventRow.id).limit(limit)
            ).all()
            return [_trace_dict(row) for row in rows]
