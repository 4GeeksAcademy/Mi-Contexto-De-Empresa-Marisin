"""Estado de los grafos de la Parte 3 (todo JSON: se guarda en el checkpoint de cada hilo).

- `DepartmentApprovalState`: la rama de **un** departamento (hilo
  `rfp-{ticket_id}:{department}`). Se interrumpe en `human_approval` y solo se
  reanuda con la decisión de su responsable.
- `TicketApprovalState`: el ticket (hilo `rfp-{ticket_id}`): conflictos,
  arbitraje, espera de los sign-offs y cierre del documento.

`trace` acumula una entrada por ejecución de nodo (agente, input, output y
timestamps) con un reductor de suma; `decisions` y `arbitrations` igual.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class DepartmentApprovalState(TypedDict, total=False):
    ticket_id: int | None
    department_id: str
    department_name: str
    responsible: str
    client_name: str | None
    currency: str | None
    context: dict[str, Any]  # DraftingInput del departamento (para reescribir)
    section: dict[str, Any]  # draft_content, draft_status, iterations, draft_source, evaluation_result, provisional
    forced: list[dict[str, Any]]  # ForcedChange pendientes del árbitro
    arbitration_notes: list[str]
    round: int  # rondas de revisión hechas en la Parte 3 (humanas o forzadas)
    max_rounds: int
    approval_requested_at: str | None
    decision: dict[str, Any] | None  # última decisión humana validada
    decisions: Annotated[list[dict[str, Any]], operator.add]
    revisions: Annotated[list[dict[str, Any]], operator.add]
    signoff: dict[str, Any] | None  # SignoffEvent al terminar
    outcome: str | None  # aprobada | rechazada
    trace: Annotated[list[dict[str, Any]], operator.add]


class TicketApprovalState(TypedDict, total=False):
    ticket_id: int | None
    rfp_id: str | None
    created_at: str | None
    drafting_handoff: dict[str, Any]  # trackflow.rfp_drafting.handoff/v1
    handoff: dict[str, Any]  # trackflow.rfp_intake.handoff/v1 (contexto de los generadores)
    client: dict[str, Any]
    currency: str | None
    monthly_volume: int | None
    departments: list[str]
    sections: dict[str, dict[str, Any]]  # borradores de la Parte 2 por departamento
    phase: str  # opening | closing
    conflicts: list[dict[str, Any]]
    arbitration_round: int
    arbitrations: Annotated[list[dict[str, Any]], operator.add]
    forced: dict[str, list[dict[str, Any]]]
    overrides: dict[str, dict[str, Any]]
    blocked: list[str]
    rejected: dict[str, str]
    pending: list[str]
    signoffs: dict[str, dict[str, Any]]  # department_id → SignoffEvent
    final_document: dict[str, Any] | None
    outcome: str | None
    trace: Annotated[list[dict[str, Any]], operator.add]
