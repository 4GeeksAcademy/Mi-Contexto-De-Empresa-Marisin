"""Avisos de los nodos de la Parte 3 al almacén (el ticket refleja cada paso en tiempo real).

Como en la Parte 2, los nodos no tocan la base de datos: llaman a un
`ApprovalReporter` que el runner implementa sobre el almacén
(`runner.StoreApprovalReporter`). Así la UI ve `pendiente → cambios_solicitados
→ pendiente → aprobada` por sección y `esperando_aprobación → terminado` en el
ticket, aunque las ramas corran en hilos distintos.
"""

from __future__ import annotations

from typing import Any, Protocol


class ApprovalReporter(Protocol):
    def approval_requested(self, ticket_id: int, department_id: str, section: dict[str, Any], *,
                           round_number: int, requested_at: str) -> None: ...
    def revising(self, ticket_id: int, department_id: str, *, round_number: int, feedback: str,
                 decision: dict[str, Any] | None = None) -> None: ...
    def revision_progress(self, ticket_id: int, department_id: str, **changes: Any) -> None: ...
    def signoff(self, ticket_id: int, department_id: str, event: dict[str, Any]) -> None: ...
    def arbitration(self, ticket_id: int, decisions: list[dict[str, Any]], rejected: dict[str, str]) -> None: ...
    def awaiting(self, ticket_id: int, pending: list[str]) -> None: ...
    def closing(self, ticket_id: int) -> None: ...
    def final_document(self, ticket_id: int, document: dict[str, Any]) -> None: ...
    def rejected(self, ticket_id: int, rejected: dict[str, str], blocked: list[str]) -> None: ...


class NullApprovalReporter:
    def approval_requested(self, ticket_id, department_id, section, *, round_number, requested_at):
        pass

    def revising(self, ticket_id, department_id, *, round_number, feedback, decision=None):
        pass

    def revision_progress(self, ticket_id, department_id, **changes):
        pass

    def signoff(self, ticket_id, department_id, event):
        pass

    def arbitration(self, ticket_id, decisions, rejected):
        pass

    def awaiting(self, ticket_id, pending):
        pass

    def closing(self, ticket_id):
        pass

    def final_document(self, ticket_id, document):
        pass

    def rejected(self, ticket_id, rejected, blocked):
        pass


class RecordingApprovalReporter(NullApprovalReporter):
    """Guarda los avisos en orden (tests)."""

    def __init__(self) -> None:
        self.events: list[tuple[Any, ...]] = []

    def approval_requested(self, ticket_id, department_id, section, *, round_number, requested_at):
        self.events.append(("approval_requested", department_id, round_number))

    def revising(self, ticket_id, department_id, *, round_number, feedback, decision=None):
        self.events.append(("revising", department_id, round_number))

    def signoff(self, ticket_id, department_id, event):
        self.events.append(("signoff", department_id, event["approval_status"]))

    def arbitration(self, ticket_id, decisions, rejected):
        self.events.append(("arbitration", tuple(d["trigger"] for d in decisions)))

    def awaiting(self, ticket_id, pending):
        self.events.append(("awaiting", tuple(pending)))

    def final_document(self, ticket_id, document):
        self.events.append(("final_document", ticket_id))

    def rejected(self, ticket_id, rejected, blocked):
        self.events.append(("rejected", tuple(sorted(rejected)), tuple(blocked)))
