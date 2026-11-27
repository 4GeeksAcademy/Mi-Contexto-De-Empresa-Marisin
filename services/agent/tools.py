"""Tools del agente de soporte: datos operativos en vivo, fuera del RAG.

Dos tools, una responsabilidad cada una, ambas de **solo lectura**:

* `lookup_tickets(TicketQuery)` → Incidents Manager, a través de las tools MCP
  `incidents_get` / `incidents_list`.
* `lookup_inventory(InventoryQuery)` → inventario, a través de la tool MCP
  `inventory_list_products`.

**Transporte: el servidor MCP de TrackFlow** (`mcps/trackflow_mcp`), como cliente
con `langchain-mcp-adapters` y OAuth (`services/agent/mcp_client.py`). El agente
ya **no** llama a la API de TrackFlow directamente: la implementación HTTP de la
Parte 2 (`http_get_json`, `AGENT_BACKEND_URL`) se eliminó para que no existan dos
caminos hacia el Incidents Manager.

Cada llamada tiene un timeout explícito de `TOOL_TIMEOUT_SECONDS` (4 s: sesión
MCP + tool). Ante timeout, servidor caído, token rechazado o error de la tool,
la tool **no lanza**: devuelve `unavailable`; ante `NOT_FOUND` o sin
coincidencias, `not_found`. El grafo enruta esos resultados al nodo
`tool_fallback`, que responde con honestidad. Los contratos (`TicketQuery`,
`TicketRecord`, `InventoryQuery`, `ProductStock`, `ToolResult`) no cambian, así
que el enrutamiento y la composición de la Parte 2 siguen igual.
"""

from __future__ import annotations

import time
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from packages.shared.incident_validation import (
    IncidentBranch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
)

from . import mcp_client

TOOL_TIMEOUT_SECONDS = mcp_client.MCP_CALL_TIMEOUT_SECONDS  # 4 s
MAX_RESULTS = 5  # tickets o productos que se muestran como máximo en la respuesta

# `forbidden`: la ACL del harness (`harness/tool_policy.py`) no deja usar la tool a ese rol;
# no se llama al servidor MCP.
ToolStatus = Literal["ok", "not_found", "unavailable", "forbidden"]


# --------------------------------------------------------------------------- #
# Contratos tipados
# --------------------------------------------------------------------------- #
class TicketQuery(BaseModel):
    """Entrada de la tool de tickets: un id concreto o filtros de búsqueda."""

    model_config = ConfigDict(extra="forbid")

    ticket_id: int | None = Field(default=None, ge=1, description="Id del ticket (incidencia).")
    status: IncidentStatus | None = None
    category: IncidentCategory | None = None
    origin: IncidentOrigin | None = None
    branch: IncidentBranch | None = None


class TicketRecord(BaseModel):
    """Salida: los mismos campos que expone `GET /api/incidents`."""

    id: str
    title: str
    description: str
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: IncidentBranch
    created_at: str
    updated_at: str


class InventoryQuery(BaseModel):
    """Entrada de la tool de inventario: código SKU o parte del nombre del producto."""

    model_config = ConfigDict(extra="forbid")

    sku: str | None = Field(default=None, min_length=1, max_length=64)
    product_name: str | None = Field(default=None, min_length=2, max_length=80)

    @model_validator(mode="after")
    def _needs_one_criterion(self) -> "InventoryQuery":
        if not (self.sku or self.product_name):
            raise ValueError("Indica un SKU o un nombre de producto")
        return self


class ProductStock(BaseModel):
    """Salida: los campos de `GET /inventory/products` (stock total entre almacenes)."""

    id: int
    sku: str
    name: str
    client_name: str
    category: str
    current_stock: int


class ToolResult(BaseModel):
    """Resultado común de una tool: estado, datos y diagnóstico."""

    tool: Literal["incidents", "inventory"]
    status: ToolStatus
    query: dict[str, Any]
    records: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    error: str | None = None
    duration_ms: float = 0.0
    fallback_message: str | None = None
    transport: Literal["mcp"] = "mcp"
    mcp_tool: str | None = None


# --------------------------------------------------------------------------- #
# Transporte: servidor MCP
# --------------------------------------------------------------------------- #
class ToolNotFound(Exception):
    """El recurso no existe (`NOT_FOUND` del servidor MCP)."""


class ToolUnavailable(Exception):
    """El servidor MCP no respondió a tiempo, rechazó el token o la tool falló."""


def call_mcp(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Único punto de salida de las tools del agente: una tool de lectura del servidor MCP."""
    try:
        return mcp_client.call_tool(tool_name, arguments)
    except mcp_client.McpCallError as exc:
        if exc.code == "NOT_FOUND":
            raise ToolNotFound(tool_name) from exc
        raise ToolUnavailable(f"{exc.code}: {exc.message}") from exc
    except mcp_client.McpUnavailable as exc:
        raise ToolUnavailable(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def _result(tool, status, query, *, records=(), total=0, error=None, started=0.0, mcp_tool=None) -> ToolResult:
    return ToolResult(
        tool=tool,
        mcp_tool=mcp_tool,
        status=status,
        query=query.model_dump(mode="json", exclude_none=True),
        records=[record.model_dump(mode="json") for record in records],
        total=total,
        error=error,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def lookup_tickets(query: TicketQuery) -> ToolResult:
    """Consulta el Incidents Manager a través del servidor MCP. Solo lectura; nunca lanza."""
    started = time.perf_counter()
    if query.ticket_id is not None:
        mcp_tool, arguments = "incidents_get", {"incident_id": query.ticket_id}
    else:
        mcp_tool = "incidents_list"
        arguments = {**query.model_dump(mode="json", exclude_none=True), "limit": MAX_RESULTS}
    try:
        payload = call_mcp(mcp_tool, arguments)
        if mcp_tool == "incidents_get":
            tickets, total = [TicketRecord.model_validate(payload)], 1
        else:
            tickets = [TicketRecord.model_validate(item) for item in payload["items"]]
            total = int(payload["total"])
    except ToolNotFound:
        return _result("incidents", "not_found", query, error="el ticket no existe", started=started, mcp_tool=mcp_tool)
    except ToolUnavailable as exc:
        return _result("incidents", "unavailable", query, error=str(exc), started=started, mcp_tool=mcp_tool)
    except (ValidationError, KeyError, TypeError, ValueError):
        return _result("incidents", "unavailable", query, error="contrato no válido en la respuesta MCP", started=started, mcp_tool=mcp_tool)

    if not tickets:
        return _result("incidents", "not_found", query, error="sin tickets con esos filtros", started=started, mcp_tool=mcp_tool)
    tickets.sort(key=lambda ticket: ticket.updated_at, reverse=True)
    return _result("incidents", "ok", query, records=tickets, total=total, started=started, mcp_tool=mcp_tool)


def fold(text: str) -> str:
    """Minúsculas y sin tildes: «Cartón» y «carton» coinciden."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def lookup_inventory(query: InventoryQuery) -> ToolResult:
    """Consulta el stock a través del servidor MCP. Solo lectura; nunca lanza."""
    started = time.perf_counter()
    mcp_tool = "inventory_list_products"
    arguments = {"sku": query.sku} if query.sku else {"name_contains": query.product_name}
    try:
        payload = call_mcp(mcp_tool, {**arguments, "limit": MAX_RESULTS})
        products = [ProductStock.model_validate(item) for item in payload["items"]]
        total = int(payload["total"])
    except (ToolUnavailable, ToolNotFound) as exc:
        return _result("inventory", "unavailable", query, error=str(exc) or "no disponible", started=started, mcp_tool=mcp_tool)
    except (ValidationError, KeyError, TypeError, ValueError):
        return _result("inventory", "unavailable", query, error="contrato no válido en la respuesta MCP", started=started, mcp_tool=mcp_tool)

    if not products:
        return _result("inventory", "not_found", query, error="sin productos que coincidan", started=started, mcp_tool=mcp_tool)
    return _result("inventory", "ok", query, records=products, total=total, started=started, mcp_tool=mcp_tool)
