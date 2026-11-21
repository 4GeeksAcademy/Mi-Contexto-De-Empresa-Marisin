"""Tools del agente de soporte: datos operativos en vivo, fuera del RAG.

Dos tools, una responsabilidad cada una, ambas de **solo lectura**:

* `lookup_tickets(TicketQuery)` → gestor de incidentes
  (`GET /api/incidents/{id}` o `GET /api/incidents?status=…&branch=…`).
* `lookup_inventory(InventoryQuery)` → gestor de inventario
  (`GET /inventory/products`).

Transporte: HTTP contra la API de TrackFlow que ya está construida
(`AGENT_BACKEND_URL`, por defecto `http://localhost:8000`). Así el agente
siempre lee el dato actual y nunca toca el almacenamiento de los servicios.
Esos endpoints de lectura no exigen autenticación hoy. Si se protegen, basta
con definir `AGENT_BACKEND_TOKEN` en el entorno y se envía como `Bearer`;
nunca hay un token escrito en el código.

Cada llamada tiene un timeout explícito de `TOOL_TIMEOUT_SECONDS` (4 s). Ante
timeout, error de red, 5xx o respuesta inválida, la tool **no lanza**: devuelve
un resultado `unavailable`; ante 404 o sin coincidencias, `not_found`. El grafo
enruta esos resultados al nodo `tool_fallback`, que responde con honestidad.
"""

from __future__ import annotations

import os
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

TOOL_TIMEOUT_SECONDS = 4.0
DEFAULT_BACKEND_URL = "http://localhost:8000"
BACKEND_URL_ENV = "AGENT_BACKEND_URL"
BACKEND_TOKEN_ENV = "AGENT_BACKEND_TOKEN"
MAX_RESULTS = 5  # tickets o productos que se muestran como máximo en la respuesta

ToolStatus = Literal["ok", "not_found", "unavailable"]


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


# --------------------------------------------------------------------------- #
# Transporte HTTP (solo GET)
# --------------------------------------------------------------------------- #
class ToolNotFound(Exception):
    """El recurso no existe (HTTP 404)."""


class ToolUnavailable(Exception):
    """El servicio no respondió a tiempo, falló o devolvió algo inválido."""


def backend_url() -> str:
    return (os.environ.get(BACKEND_URL_ENV) or DEFAULT_BACKEND_URL).rstrip("/")


def auth_headers() -> dict[str, str]:
    token = (os.environ.get(BACKEND_TOKEN_ENV) or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


# Los tests sustituyen el transporte de httpx (httpx.MockTransport) aquí.
HTTP_TRANSPORT = None


def http_get_json(path: str, params: dict[str, Any] | None = None) -> Any:
    """Único punto de salida HTTP de las tools: **GET** con timeout de 4 s."""
    import httpx

    try:
        with httpx.Client(
            base_url=backend_url(),
            timeout=httpx.Timeout(TOOL_TIMEOUT_SECONDS),
            headers=auth_headers(),
            transport=HTTP_TRANSPORT,
        ) as client:
            response = client.get(path, params=params or None)
    except httpx.TimeoutException as exc:
        raise ToolUnavailable(f"timeout: sin respuesta en {TOOL_TIMEOUT_SECONDS:g} s") from exc
    except httpx.HTTPError as exc:
        raise ToolUnavailable(f"error de conexión: {type(exc).__name__}") from exc

    if response.status_code == 404:
        raise ToolNotFound(path)
    if response.status_code >= 400:
        raise ToolUnavailable(f"HTTP {response.status_code} en GET {path}")
    try:
        return response.json()
    except ValueError as exc:
        raise ToolUnavailable(f"respuesta no JSON en GET {path}") from exc


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
def _result(tool, status, query, *, records=(), total=0, error=None, started=0.0) -> ToolResult:
    return ToolResult(
        tool=tool,
        status=status,
        query=query.model_dump(mode="json", exclude_none=True),
        records=[record.model_dump(mode="json") for record in records],
        total=total,
        error=error,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def lookup_tickets(query: TicketQuery) -> ToolResult:
    """Consulta el gestor de incidentes. Solo lectura; nunca lanza."""
    started = time.perf_counter()
    try:
        if query.ticket_id is not None:
            payload = http_get_json(f"/api/incidents/{query.ticket_id}")
            tickets = [TicketRecord.model_validate(payload)]
        else:
            filters = query.model_dump(mode="json", exclude_none=True)
            payload = http_get_json("/api/incidents", params=filters)
            if not isinstance(payload, list):
                raise ToolUnavailable("GET /api/incidents no devolvió una lista")
            tickets = [TicketRecord.model_validate(item) for item in payload]
    except ToolNotFound:
        return _result("incidents", "not_found", query, error="el ticket no existe", started=started)
    except ToolUnavailable as exc:
        return _result("incidents", "unavailable", query, error=str(exc), started=started)
    except ValidationError as exc:
        return _result("incidents", "unavailable", query, error=f"contrato no válido: {exc.error_count()} errores", started=started)

    if not tickets:
        return _result("incidents", "not_found", query, error="sin tickets con esos filtros", started=started)
    tickets.sort(key=lambda ticket: ticket.updated_at, reverse=True)
    return _result("incidents", "ok", query, records=tickets[:MAX_RESULTS], total=len(tickets), started=started)


def fold(text: str) -> str:
    """Minúsculas y sin tildes: «Cartón» y «carton» coinciden."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def _matches(product: ProductStock, query: InventoryQuery) -> bool:
    if query.sku:
        return product.sku.strip().lower() == query.sku.strip().lower()
    return fold(query.product_name.strip()) in fold(product.name)


def lookup_inventory(query: InventoryQuery) -> ToolResult:
    """Consulta el stock en el gestor de inventario. Solo lectura; nunca lanza."""
    started = time.perf_counter()
    try:
        payload = http_get_json("/inventory/products")
        if not isinstance(payload, list):
            raise ToolUnavailable("GET /inventory/products no devolvió una lista")
        products = [ProductStock.model_validate(item) for item in payload]
    except (ToolUnavailable, ToolNotFound) as exc:
        return _result("inventory", "unavailable", query, error=str(exc) or "no disponible", started=started)
    except ValidationError as exc:
        return _result("inventory", "unavailable", query, error=f"contrato no válido: {exc.error_count()} errores", started=started)

    found = [product for product in products if _matches(product, query)]
    if not found:
        return _result("inventory", "not_found", query, error="sin productos que coincidan", started=started)
    return _result("inventory", "ok", query, records=found[:MAX_RESULTS], total=len(found), started=started)
