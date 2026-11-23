"""Estado del grafo `rfp_intake`.

`RfpState` es el estado compartido; cada worker recibe en cambio un `WorkerInput`
propio (vía `Send`) con solo su workstream y los metadatos: nunca el documento
completo ni las secciones de otros departamentos. `sections` se acumula con un
reductor de suma: los workers corren en paralelo y cada uno añade la suya.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class RfpState(TypedDict, total=False):
    ticket_id: int | None
    rfp_id: str | None
    pdf_path: str
    markdown: str
    classification: dict[str, Any]
    metadata: dict[str, Any]
    readability: dict[str, Any]
    workstreams: list[dict[str, Any]]
    inactive_departments: list[dict[str, str]]
    unassigned_requests: list[dict[str, str]]
    orchestrator: dict[str, Any]
    sections: Annotated[list[dict[str, Any]], operator.add]
    handoff: dict[str, Any]
    outcome: str  # "discarded" | "analysis_complete"


class WorkerInput(TypedDict):
    workstream: dict[str, Any]
    metadata: dict[str, Any]
