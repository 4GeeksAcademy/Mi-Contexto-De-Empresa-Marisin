"""Lógica de las tools, independiente del transporte MCP (se prueba sin red).

Cada tool declara su política (scope requerido y modo de acceso) en
`TOOL_POLICIES`, que es la fuente de verdad de los permisos. Mínimo privilegio:

| Tool | Scope | Acceso |
|---|---|---|
| `incidents_list`, `incidents_get` | `incidents:read` | lectura |
| `incidents_create`, `incidents_update_status` | `incidents:write` | escritura (vía el Incidents Manager) |
| `inventory_list_products`, `inventory_get_product` | `inventory:read` | lectura |
| `inventory_update_stock` | — | **siempre rechazada** (`READ_ONLY_RESOURCE`) |
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from pydantic import ValidationError

from .backend import BackendClient
from .config import SCOPE_INCIDENTS_READ, SCOPE_INCIDENTS_WRITE, SCOPE_INVENTORY_READ
from .errors import McpToolError
from .models import Incident, IncidentList, Product, ProductList, with_lifecycle


@dataclass(frozen=True)
class ToolPolicy:
    scope: str | None
    access: Literal["read", "write", "forbidden"]
    resource: Literal["incidents", "inventory"]


TOOL_POLICIES = {
    "incidents_list": ToolPolicy(SCOPE_INCIDENTS_READ, "read", "incidents"),
    "incidents_get": ToolPolicy(SCOPE_INCIDENTS_READ, "read", "incidents"),
    "incidents_create": ToolPolicy(SCOPE_INCIDENTS_WRITE, "write", "incidents"),
    "incidents_update_status": ToolPolicy(SCOPE_INCIDENTS_WRITE, "write", "incidents"),
    "inventory_list_products": ToolPolicy(SCOPE_INVENTORY_READ, "read", "inventory"),
    "inventory_get_product": ToolPolicy(SCOPE_INVENTORY_READ, "read", "inventory"),
    "inventory_update_stock": ToolPolicy(None, "forbidden", "inventory"),
}


@dataclass(frozen=True)
class Caller:
    """Identidad del cliente MCP, sacada del access token ya validado por MCP Auth."""

    client_id: str | None
    subject: str | None
    scopes: list[str] = field(default_factory=list)


def authorize(tool: str, caller: Caller) -> None:
    """Aplica la política de la tool: solo lectura explícita y scope requerido."""
    policy = TOOL_POLICIES[tool]
    if policy.access == "forbidden":
        raise McpToolError(
            "READ_ONLY_RESOURCE",
            "El inventario es de solo lectura a través de este servidor MCP. Para cambiar el stock hay que "
            "registrar una orden de entrada o salida en el sistema de inventario; ningún token puede hacerlo aquí.",
            tool=tool,
        )
    if policy.scope not in caller.scopes:
        raise McpToolError(
            "INSUFFICIENT_SCOPE",
            f"El access token no tiene el scope '{policy.scope}' que exige la tool {tool}.",
            required_scope=policy.scope,
            granted_scopes=sorted(caller.scopes),
        )


def fold(text: str) -> str:
    """Minúsculas y sin tildes: «Cartón» y «carton» coinciden."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def parse(model, payload):
    """Valida lo que devuelve la API contra el contrato; si no encaja, es un fallo del servicio, no del cliente."""
    try:
        return model(payload)
    except ValidationError as exc:
        raise McpToolError(
            "UPSTREAM_UNAVAILABLE", "La API de TrackFlow devolvió datos que no cumplen el contrato."
        ) from exc


class TrackFlowTools:
    def __init__(self, backend: BackendClient):
        self.backend = backend

    # ----------------------------------------------------------------- incidencias
    def incidents_list(
        self, caller: Caller, *, status=None, category=None, origin=None, branch=None, limit: int = 20
    ) -> IncidentList:
        authorize("incidents_list", caller)
        filters = {"status": status, "category": category, "origin": origin, "branch": branch}
        params = {key: getattr(value, "value", value) for key, value in filters.items() if value is not None}
        payload = self.backend.request("GET", "/api/incidents", params=params)
        if not isinstance(payload, list):
            raise McpToolError("UPSTREAM_UNAVAILABLE", "GET /api/incidents no devolvió una lista.")
        incidents = sorted((parse(with_lifecycle, item) for item in payload), key=lambda i: i.updated_at, reverse=True)
        return IncidentList(total=len(incidents), items=incidents[:limit])

    def incidents_get(self, caller: Caller, *, incident_id: int) -> Incident:
        authorize("incidents_get", caller)
        return parse(with_lifecycle, self.backend.request("GET", f"/api/incidents/{incident_id}"))

    def incidents_create(self, caller: Caller, *, title, description, category, origin, branch) -> Incident:
        authorize("incidents_create", caller)
        body = {
            "title": title,
            "description": description,
            "category": getattr(category, "value", category),
            "origin": getattr(origin, "value", origin),
            "branch": getattr(branch, "value", branch),
        }  # el estado inicial lo fija el Incidents Manager: siempre "open"
        return parse(with_lifecycle, self.backend.request("POST", "/api/incidents", json=body))

    def incidents_update_status(self, caller: Caller, *, incident_id: int, status) -> Incident:
        authorize("incidents_update_status", caller)
        body = {"status": getattr(status, "value", status)}
        return parse(with_lifecycle, self.backend.request("PATCH", f"/api/incidents/{incident_id}/status", json=body))

    # ----------------------------------------------------------------- inventario
    def inventory_list_products(
        self, caller: Caller, *, sku: str | None = None, name_contains: str | None = None, limit: int = 20
    ) -> ProductList:
        authorize("inventory_list_products", caller)
        payload = self.backend.request("GET", "/inventory/products")
        if not isinstance(payload, list):
            raise McpToolError("UPSTREAM_UNAVAILABLE", "GET /inventory/products no devolvió una lista.")
        products = [parse(Product.model_validate, item) for item in payload]
        if sku:
            products = [p for p in products if p.sku.lower() == sku.strip().lower()]
        if name_contains:
            needle = fold(name_contains.strip())
            products = [p for p in products if needle in fold(p.name)]
        return ProductList(total=len(products), items=products[:limit])

    def inventory_get_product(self, caller: Caller, *, product_id: int) -> Product:
        authorize("inventory_get_product", caller)
        return parse(Product.model_validate, self.backend.request("GET", f"/inventory/products/{product_id}"))

    def inventory_update_stock(self, caller: Caller, **_ignored) -> None:
        authorize("inventory_update_stock", caller)  # siempre lanza READ_ONLY_RESOURCE
