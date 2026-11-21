"""Contratos de salida de las tools (aparecen como `outputSchema` en el discovery).

Los nombres de campos y los valores de dominio son los del Incidents Manager
(`services/api/models.py` → `Incident`) y del inventario (`ProductListItem`):
mismos enums (`packages/shared/incident_validation.py`) y mismos ids.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from packages.shared.incident_validation import (
    IncidentBranch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
)

# Ciclo de vida del Incidents Manager (services/api/services/incidents.py → ALLOWED_TRANSITIONS).
ALLOWED_TRANSITIONS = {
    "open": ["in_progress", "discarded"],
    "in_progress": ["resolved", "discarded"],
    "resolved": [],
    "discarded": [],
}


class Incident(BaseModel):
    """Incidencia tal como la expone `GET /api/incidents/{id}`."""

    id: str = Field(description="Id de la incidencia en el Incidents Manager (texto con un entero, p. ej. \"3\").")
    title: str
    description: str
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: IncidentBranch
    created_at: str = Field(description="Fecha de creación (ISO 8601, UTC).")
    updated_at: str = Field(description="Última actualización (ISO 8601, UTC).")
    allowed_next_statuses: list[IncidentStatus] = Field(
        default_factory=list,
        description="Estados a los que se puede pasar desde el actual con incidents_update_status.",
    )


class IncidentList(BaseModel):
    """Resultado de una búsqueda de incidencias."""

    total: int = Field(description="Incidencias que cumplen los filtros.")
    items: list[Incident] = Field(description="Incidencias, de la actualizada más recientemente a la más antigua (máx. `limit`).")


class Product(BaseModel):
    """Producto del inventario con su stock total entre almacenes (`GET /inventory/products`)."""

    id: int = Field(description="Id del producto (SKU) en el inventario.")
    sku: str
    name: str
    client_name: str = Field(description="Marca cliente propietaria del inventario.")
    category: str
    reference: str = ""
    current_stock: int = Field(description="Unidades en stock, sumando los almacenes de Los Ángeles y Zaragoza.")


class ProductList(BaseModel):
    """Resultado de una consulta de inventario."""

    total: int = Field(description="Productos que cumplen el filtro.")
    items: list[Product] = Field(description="Productos (máx. `limit`), ordenados por id.")


def with_lifecycle(payload: dict) -> Incident:
    incident = Incident.model_validate(payload)
    incident.allowed_next_statuses = [IncidentStatus(s) for s in ALLOWED_TRANSITIONS.get(incident.status.value, [])]
    return incident
