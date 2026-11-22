"""Persistencia del ticket RFP en PostgreSQL (Supabase) con SQLModel.

Tres tablas en `public` (DDL idempotente con checks, índices y RLS en
`services/sql/003_rfp_intake.sql`; `SQLModel.metadata.create_all` al arrancar la
API también las crea si faltan, sin los checks):

- `rfp_tickets`: el ticket y su ciclo de vida (`status`, `stage`, PDF en
  `data/raw/rfp/`, Markdown convertido —la Parte 2 no vuelve a leer el PDF—,
  clasificación, error, handoff y la bandera `ready_for_drafting` que lee la Parte 2).
- `rfp_metadata`: metadatos de la RFP (BRIEFING §2.3) y métricas de legibilidad.
- `rfp_department_sections`: una fila por departamento activo con `key_aspects`;
  `draft_content`, `evaluation_results`, `approval_status`, `approver` y
  `approved_at` quedan a `NULL` para las Partes 2 y 3.

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
from .store import TicketNotFound, utc_now


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
    approval_status: Optional[str] = None
    approver: Optional[str] = None
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


RFP_TABLES = [RfpTicket.__table__, RfpMetadataRow.__table__, RfpDepartmentSectionRow.__table__]

_METADATA_FIELDS = (
    "client_name", "client_reference", "client_country", "currency", "services_requested", "monthly_volume",
    "deadline_text", "budget_range", "contact", "departments_needed", "warnings",
)
_SECTION_FIELDS = (
    "department_id", "department_name", "responsible", "key_aspects", "open_questions", "excerpts", "source",
    "warnings", "draft_content", "evaluation_results", "approval_status", "approver", "approved_at",
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
            session.execute(delete(RfpDepartmentSectionRow).where(RfpDepartmentSectionRow.ticket_id == ticket_id))
            session.execute(delete(RfpMetadataRow).where(RfpMetadataRow.ticket_id == ticket_id))
            row.status = config.STATUS_ANALYZING
            row.stage = config.STAGE_CONVERTING
            row.classification = None
            row.error_stage = None
            row.error_message = None
            row.handoff = None
            row.ready_for_drafting = False
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
