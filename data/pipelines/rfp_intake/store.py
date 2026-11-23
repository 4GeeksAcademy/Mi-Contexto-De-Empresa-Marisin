"""Interfaz de persistencia del ticket RFP y su implementación en memoria.

La fuente de verdad en producción es PostgreSQL (Supabase): `sql_store.SqlRfpStore`.
`InMemoryRfpStore` existe para los tests y para `scripts/rfp_intake_run.py --dry-run`;
nunca se usa como almacenamiento real.

Un ticket se representa siempre como el mismo `dict` (ver `TICKET_FIELDS`), con
`metadata` y `sections` añadidos en `get_ticket()`.
"""

from __future__ import annotations

import copy
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from . import config
from .drafting import config as drafting_config

TICKET_FIELDS = (
    "ticket_id", "rfp_id", "status", "stage", "raw_pdf_path", "original_filename", "file_sha256",
    "file_size_bytes", "uploaded_by", "classification", "error_stage", "error_message", "handoff",
    "ready_for_drafting", "drafting_handoff", "ready_for_approval", "markdown_chars", "created_at", "updated_at",
)
# Campos de la Parte 2 en cada sección (vacíos hasta que se genera el borrador).
SECTION_DRAFT_DEFAULTS = {
    "draft_content": None, "evaluation_results": None, "draft_status": None, "iterations": 0,
    "evaluation_history": [], "draft_source": None,
}
# Estados en los que hay un pipeline trabajando (Parte 1 o Parte 2).
WORKING_STATUSES = (config.STATUS_ANALYZING, drafting_config.STATUS_GENERATING, drafting_config.STATUS_EVALUATING)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_working(ticket: dict[str, Any]) -> bool:
    """Hay un pipeline en curso: analizando (Parte 1) o generando/evaluando borradores (Parte 2)."""
    return (
        ticket.get("status") in WORKING_STATUSES
        and ticket.get("stage") not in (config.STAGE_ERROR, drafting_config.STAGE_DRAFTS_READY)
    )


def is_stale(ticket: dict[str, Any], now: datetime | None = None) -> bool:
    """En curso, sin actividad reciente y sin error registrado: el proceso murió a mitad."""
    if not is_working(ticket):
        return False
    updated_at = ticket.get("updated_at")
    if not isinstance(updated_at, datetime):
        return False
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return (now or utc_now()) - updated_at > timedelta(minutes=config.STALE_AFTER_MINUTES)


class RfpStore(Protocol):
    def create_ticket(self, *, rfp_id: str, raw_pdf_path: str, original_filename: str, file_sha256: str,
                      file_size_bytes: int, uploaded_by: str | None) -> dict[str, Any]: ...
    def get_ticket(self, ticket_id: int) -> dict[str, Any] | None: ...
    def list_tickets(self, limit: int = 50) -> list[dict[str, Any]]: ...
    def start_processing(self, ticket_id: int) -> None: ...
    def set_stage(self, ticket_id: int, stage: str) -> None: ...
    def save_markdown(self, ticket_id: int, markdown: str) -> None: ...
    def get_markdown(self, ticket_id: int) -> str | None: ...
    def save_classification(self, ticket_id: int, classification: dict[str, Any], stage: str) -> None: ...
    def discard(self, ticket_id: int) -> None: ...
    def save_metadata(self, ticket_id: int, metadata: dict[str, Any], readability: dict[str, Any]) -> None: ...
    def save_section(self, ticket_id: int, section: dict[str, Any]) -> None: ...
    def complete(self, ticket_id: int, handoff: dict[str, Any]) -> None: ...
    def fail(self, ticket_id: int, stage: str, message: str) -> None: ...
    # Parte 2 · generación y evaluación de borradores
    def list_ready_for_drafting(self, limit: int = 50) -> list[dict[str, Any]]: ...
    def claim_for_drafting(self, ticket_id: int, *, force: bool = False) -> dict[str, Any]: ...
    def set_drafting_progress(self, ticket_id: int, status: str, stage: str) -> None: ...
    def save_section_draft(self, ticket_id: int, department_id: str, **changes: Any) -> None: ...
    def complete_drafting(self, ticket_id: int, output: dict[str, Any]) -> None: ...


class TicketNotFound(LookupError):
    pass


class NotDraftable(ValueError):
    """El ticket no puede pasar a la Parte 2 (sin handoff, descartado, ya en curso…)."""


def drafting_refusal(ticket: dict[str, Any], *, force: bool = False) -> str | None:
    """Motivo por el que el ticket no puede (re)generar borradores, o `None` si puede.

    Sin `force` solo entra lo que está en la cola de la Parte 1
    (`analisis_completo` + `ready_for_drafting`). Con `force` (relanzar desde la
    UI o el CLI) también un ticket de la Parte 2 que terminó, falló o se quedó
    parado; nunca uno que está trabajando ahora mismo.
    """
    handoff = ticket.get("handoff") or {}
    status = ticket.get("status")
    if status not in drafting_config.DRAFTABLE_STATUSES:
        return f"el ticket está en «{status}»: la Parte 2 solo parte de un análisis completo"
    if not handoff.get("departments"):
        return "el ticket no tiene handoff de la Parte 1 con departamentos activos"
    if status == config.STATUS_ANALYSIS_COMPLETE:
        if not ticket.get("ready_for_drafting") and not force:
            return "el ticket no está en la cola de redacción (ready_for_drafting = false)"
        return None
    if not force:
        return "el ticket ya pasó por la Parte 2: relánzalo de forma explícita"
    if is_working(ticket) and not is_stale(ticket):
        return "los borradores de este ticket se están generando ahora mismo"
    return None


class InMemoryRfpStore:
    """Misma semántica que `SqlRfpStore`, en diccionarios (tests y dry-run)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_id = 1
        self.tickets: dict[int, dict[str, Any]] = {}
        self.markdown: dict[int, str] = {}
        self.metadata: dict[int, dict[str, Any]] = {}
        self.sections: dict[int, dict[str, dict[str, Any]]] = {}

    def _ticket(self, ticket_id: int) -> dict[str, Any]:
        try:
            return self.tickets[ticket_id]
        except KeyError:
            raise TicketNotFound(ticket_id) from None

    def _touch(self, ticket: dict[str, Any], **changes: Any) -> None:
        ticket.update(changes)
        ticket["updated_at"] = utc_now()

    def create_ticket(self, *, rfp_id, raw_pdf_path, original_filename, file_sha256, file_size_bytes, uploaded_by):
        with self._lock:
            ticket_id = self._next_id
            self._next_id += 1
            now = utc_now()
            self.tickets[ticket_id] = {
                "ticket_id": ticket_id, "rfp_id": rfp_id, "status": config.STATUS_ANALYZING,
                "stage": config.STAGE_RECEIVED, "raw_pdf_path": raw_pdf_path, "original_filename": original_filename,
                "file_sha256": file_sha256, "file_size_bytes": file_size_bytes, "uploaded_by": uploaded_by,
                "classification": None, "error_stage": None, "error_message": None, "handoff": None,
                "ready_for_drafting": False, "drafting_handoff": None, "ready_for_approval": False,
                "markdown_chars": None, "created_at": now, "updated_at": now,
            }
            return copy.deepcopy(self.tickets[ticket_id])

    def get_ticket(self, ticket_id):
        with self._lock:
            ticket = self.tickets.get(ticket_id)
            if ticket is None:
                return None
            result = copy.deepcopy(ticket)
            result["metadata"] = copy.deepcopy(self.metadata.get(ticket_id))
            result["sections"] = [
                copy.deepcopy(self.sections[ticket_id][dept])
                for dept in config.DEPARTMENT_ORDER
                if dept in self.sections.get(ticket_id, {})
            ]
            return result

    def list_tickets(self, limit=50):
        with self._lock:
            ordered = sorted(self.tickets.values(), key=lambda t: t["ticket_id"], reverse=True)[:limit]
            result = []
            for ticket in ordered:
                item = copy.deepcopy(ticket)
                item["client_name"] = (self.metadata.get(ticket["ticket_id"]) or {}).get("client_name")
                result.append(item)
            return result

    def start_processing(self, ticket_id):
        with self._lock:
            ticket = self._ticket(ticket_id)
            self.metadata.pop(ticket_id, None)
            self.sections.pop(ticket_id, None)
            self._touch(ticket, status=config.STATUS_ANALYZING, stage=config.STAGE_CONVERTING, classification=None,
                        error_stage=None, error_message=None, handoff=None, ready_for_drafting=False,
                        drafting_handoff=None, ready_for_approval=False)

    def set_stage(self, ticket_id, stage):
        with self._lock:
            self._touch(self._ticket(ticket_id), stage=stage)

    def save_markdown(self, ticket_id, markdown):
        with self._lock:
            self.markdown[ticket_id] = markdown
            self._touch(self._ticket(ticket_id), markdown_chars=len(markdown))

    def get_markdown(self, ticket_id):
        with self._lock:
            return self.markdown.get(ticket_id)

    def save_classification(self, ticket_id, classification, stage):
        with self._lock:
            self._touch(self._ticket(ticket_id), classification=copy.deepcopy(classification), stage=stage)

    def discard(self, ticket_id):
        with self._lock:
            self._touch(self._ticket(ticket_id), status=config.STATUS_DISCARDED, stage=config.STAGE_DISCARDED)

    def save_metadata(self, ticket_id, metadata, readability):
        with self._lock:
            self._ticket(ticket_id)
            self.metadata[ticket_id] = {**copy.deepcopy(metadata), "readability": copy.deepcopy(readability)}
            self._touch(self._ticket(ticket_id), stage=config.STAGE_ORCHESTRATING)

    def save_section(self, ticket_id, section):
        with self._lock:
            self._ticket(ticket_id)
            self.sections.setdefault(ticket_id, {})[section["department_id"]] = {
                **copy.deepcopy(section), **copy.deepcopy(SECTION_DRAFT_DEFAULTS),
                "approval_status": None, "approver": None, "approved_at": None,
            }
            self._touch(self._ticket(ticket_id), stage=config.STAGE_DEPARTMENTS)

    def complete(self, ticket_id, handoff):
        with self._lock:
            self._touch(self._ticket(ticket_id), status=config.STATUS_ANALYSIS_COMPLETE, stage=config.STAGE_DONE,
                        handoff=copy.deepcopy(handoff), ready_for_drafting=bool(handoff.get("ready_for_drafting")))

    def fail(self, ticket_id, stage, message):
        with self._lock:
            ticket = self.tickets.get(ticket_id)
            if ticket is not None:
                self._touch(ticket, stage=config.STAGE_ERROR, error_stage=stage, error_message=message[:2000])

    # ------------------------------------------------------------------ #
    # Parte 2
    # ------------------------------------------------------------------ #
    def list_ready_for_drafting(self, limit=50):
        with self._lock:
            ready = [
                copy.deepcopy(t) for t in sorted(self.tickets.values(), key=lambda t: t["ticket_id"])
                if t["status"] == config.STATUS_ANALYSIS_COMPLETE and t["ready_for_drafting"]
            ]
            return ready[:limit]

    def claim_for_drafting(self, ticket_id, *, force=False):
        with self._lock:
            ticket = self._ticket(ticket_id)
            reason = drafting_refusal(ticket, force=force)
            if reason:
                raise NotDraftable(reason)
            self._touch(ticket, status=drafting_config.STATUS_GENERATING, stage=drafting_config.STAGE_GENERATING,
                        ready_for_drafting=False, drafting_handoff=None, ready_for_approval=False,
                        error_stage=None, error_message=None)
            for section in self.sections.get(ticket_id, {}).values():
                section.update(copy.deepcopy(SECTION_DRAFT_DEFAULTS))
            return copy.deepcopy(ticket)

    def set_drafting_progress(self, ticket_id, status, stage):
        with self._lock:
            self._touch(self._ticket(ticket_id), status=status, stage=stage)

    def save_section_draft(self, ticket_id, department_id, **changes):
        with self._lock:
            ticket = self._ticket(ticket_id)
            section = self.sections.get(ticket_id, {}).get(department_id)
            if section is None:
                raise KeyError(f"El ticket {ticket_id} no tiene sección {department_id}")
            entry = changes.pop("history_entry", None)
            section.update(copy.deepcopy(changes))
            if entry is not None:
                section["evaluation_history"] = [*(section.get("evaluation_history") or []), copy.deepcopy(entry)]
            self._touch(ticket)

    def complete_drafting(self, ticket_id, output):
        with self._lock:
            self._touch(self._ticket(ticket_id), status=output["status"], stage=drafting_config.STAGE_DRAFTS_READY,
                        drafting_handoff=copy.deepcopy(output), ready_for_approval=bool(output.get("ready_for_approval")))
