"""Pruebas de las tools del agente con un transporte HTTP simulado (`httpx.MockTransport`).

Se comprueba el contrato tipado, que la única operación es `GET`, el timeout
numérico de 4 s, el uso opcional del token del entorno y que cualquier fallo
del servicio se convierte en `not_found` / `unavailable` en vez de lanzar.

    python -m pytest tests/pipelines/test_agent_tools.py
"""

import inspect

import httpx
import pytest
from pydantic import ValidationError

from services.agent import tools

TICKET = {
    "id": "3",
    "title": "Caja aplastada en destino",
    "description": "El cliente recibe la caja aplastada",
    "category": "DAMAGE",
    "status": "in_progress",
    "origin": "customer",
    "branch": "Zaragoza",
    "created_at": "2026-11-10T09:00:00+00:00",
    "updated_at": "2026-11-15T12:00:00+00:00",
}
OLDER = {**TICKET, "id": "1", "status": "open", "updated_at": "2026-11-01T08:00:00+00:00"}
PRODUCTS = [
    {"id": 1, "sku": "TF-BOX-001", "name": "Cajas de cartón XL", "client_name": "PackCo", "category": "embalaje", "reference": "R1", "current_stock": 120},
    {"id": 2, "sku": "TF-ZAP-002", "name": "Zapatillas running", "client_name": "RunCo", "category": "calzado", "reference": "R2", "current_stock": 0},
]


@pytest.fixture
def backend(monkeypatch):
    """Servicio simulado: registra cada petición y responde según la ruta."""
    state = {"requests": [], "mode": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        if state["mode"] == "timeout":
            raise httpx.ReadTimeout("sin respuesta", request=request)
        if state["mode"] == "down":
            raise httpx.ConnectError("conexión rechazada", request=request)
        if state["mode"] == "error":
            return httpx.Response(500, json={"detail": "boom"})
        if state["mode"] == "garbage":
            return httpx.Response(200, json={"unexpected": True})
        path = request.url.path
        if path == "/api/incidents/3":
            return httpx.Response(200, json=TICKET)
        if path.startswith("/api/incidents/"):
            return httpx.Response(404, json={"detail": "La incidencia no existe"})
        if path == "/api/incidents":
            items = [OLDER, TICKET]
            for key, value in request.url.params.items():
                items = [item for item in items if item.get(key) == value]
            return httpx.Response(200, json=items)
        if path == "/inventory/products":
            return httpx.Response(200, json=PRODUCTS)
        return httpx.Response(404)

    monkeypatch.setattr(tools, "HTTP_TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.delenv(tools.BACKEND_TOKEN_ENV, raising=False)
    monkeypatch.setenv(tools.BACKEND_URL_ENV, "http://api.test")
    return state


# --------------------------------------------------------------------------- #
# Contratos
# --------------------------------------------------------------------------- #
def test_ticket_query_contract_is_typed_and_strict():
    assert tools.TicketQuery(ticket_id=482).ticket_id == 482
    assert tools.TicketQuery(status="open", branch="Zaragoza").status.value == "open"
    for bad in ({"ticket_id": 0}, {"status": "cerrado"}, {"branch": "Madrid"}, {"priority": "high"}):
        with pytest.raises(ValidationError):
            tools.TicketQuery(**bad)


def test_inventory_query_needs_a_sku_or_a_product_name():
    with pytest.raises(ValidationError):
        tools.InventoryQuery()
    assert tools.InventoryQuery(sku="TF-BOX-001").sku == "TF-BOX-001"


# --------------------------------------------------------------------------- #
# Tool de tickets
# --------------------------------------------------------------------------- #
def test_ticket_by_id_reads_the_real_endpoint(backend):
    result = tools.lookup_tickets(tools.TicketQuery(ticket_id=3))

    assert result.status == "ok"
    assert result.records == [tools.TicketRecord.model_validate(TICKET).model_dump(mode="json")]
    request = backend["requests"][0]
    assert (request.method, str(request.url)) == ("GET", "http://api.test/api/incidents/3")


def test_ticket_search_passes_filters_and_sorts_by_last_update(backend):
    result = tools.lookup_tickets(tools.TicketQuery(branch="Zaragoza"))

    assert result.status == "ok" and result.total == 2
    assert [ticket["id"] for ticket in result.records] == ["3", "1"]
    assert dict(backend["requests"][0].url.params) == {"branch": "Zaragoza"}


def test_missing_ticket_is_not_found(backend):
    result = tools.lookup_tickets(tools.TicketQuery(ticket_id=999999))
    assert result.status == "not_found" and result.records == []


def test_search_without_matches_is_not_found(backend):
    assert tools.lookup_tickets(tools.TicketQuery(status="discarded")).status == "not_found"


@pytest.mark.parametrize("mode", ["timeout", "down", "error", "garbage"])
def test_any_service_failure_is_unavailable_and_never_raises(backend, mode):
    backend["mode"] = mode
    result = tools.lookup_tickets(tools.TicketQuery(ticket_id=3))
    assert result.status == "unavailable"
    assert result.records == []
    assert result.error


def test_timeout_is_explicit_numeric_and_reported(backend):
    assert tools.TOOL_TIMEOUT_SECONDS == 4.0
    tools.lookup_tickets(tools.TicketQuery(ticket_id=3))
    assert set(backend["requests"][0].extensions["timeout"].values()) == {4.0}

    backend["mode"] = "timeout"
    assert "4 s" in tools.lookup_tickets(tools.TicketQuery(ticket_id=3)).error


def test_no_auth_header_unless_a_token_is_configured(backend, monkeypatch):
    tools.lookup_tickets(tools.TicketQuery(ticket_id=3))
    assert "authorization" not in backend["requests"][-1].headers

    monkeypatch.setenv(tools.BACKEND_TOKEN_ENV, "token-de-servicio")
    tools.lookup_tickets(tools.TicketQuery(ticket_id=3))
    assert backend["requests"][-1].headers["authorization"] == "Bearer token-de-servicio"


# --------------------------------------------------------------------------- #
# Tool de inventario
# --------------------------------------------------------------------------- #
def test_inventory_by_sku_ignores_case(backend):
    result = tools.lookup_inventory(tools.InventoryQuery(sku="tf-box-001"))
    assert result.status == "ok"
    assert result.records[0]["current_stock"] == 120
    assert backend["requests"][0].url.path == "/inventory/products"


def test_inventory_by_name_ignores_accents(backend):
    result = tools.lookup_inventory(tools.InventoryQuery(product_name="cajas de carton"))
    assert [product["sku"] for product in result.records] == ["TF-BOX-001"]


def test_inventory_not_found_and_unavailable(backend):
    assert tools.lookup_inventory(tools.InventoryQuery(sku="NO-EXISTE")).status == "not_found"
    backend["mode"] = "timeout"
    assert tools.lookup_inventory(tools.InventoryQuery(sku="TF-BOX-001")).status == "unavailable"


# --------------------------------------------------------------------------- #
# Solo lectura
# --------------------------------------------------------------------------- #
def test_tools_are_read_only(backend):
    tools.lookup_tickets(tools.TicketQuery(ticket_id=3))
    tools.lookup_tickets(tools.TicketQuery(status="open"))
    tools.lookup_inventory(tools.InventoryQuery(sku="TF-BOX-001"))

    assert {request.method for request in backend["requests"]} == {"GET"}
    source = inspect.getsource(tools)
    for verb in (".post(", ".put(", ".patch(", ".delete(", ".request(", "method="):
        assert verb not in source
