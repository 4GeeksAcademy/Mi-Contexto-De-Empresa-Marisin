"""Pruebas de las tools del agente tras la migración al servidor MCP.

Las tools del agente (`lookup_tickets`, `lookup_inventory`) ya no llaman a la API
de TrackFlow: invocan tools del servidor MCP con `langchain-mcp-adapters` y un
token OAuth de solo lectura. Aquí se sustituye la llamada MCP por un doble y se
comprueba el contrato, el mapeo de errores a `not_found` / `unavailable`, el
cliente OAuth y que no queda ningún camino directo hacia el Incidents Manager.

    python -m pytest tests/pipelines/test_agent_tools.py
"""

import ast
import asyncio
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from services.agent import mcp_client, tools

AGENT_DIR = Path(__file__).resolve().parents[2] / "services" / "agent"
TICKET = {
    "id": "3", "title": "Caja aplastada en destino", "description": "d", "category": "DAMAGE",
    "status": "in_progress", "origin": "customer", "branch": "Zaragoza",
    "created_at": "2026-11-10T09:00:00+00:00", "updated_at": "2026-11-15T12:00:00+00:00",
    "allowed_next_statuses": ["resolved", "discarded"],
}
PRODUCT = {"id": 1, "sku": "TF-BOX-001", "name": "Cajas de cartón XL", "client_name": "PackCo",
           "category": "embalaje", "reference": "R1", "current_stock": 120}


@pytest.fixture
def mcp(monkeypatch):
    """Servidor MCP simulado: registra (tool, argumentos) y responde como el real."""
    state = {"calls": [], "mode": "ok"}

    def fake_call_tool(name, arguments):
        state["calls"].append((name, arguments))
        if state["mode"] == "down":
            raise mcp_client.McpUnavailable("timeout: el servidor MCP no respondió en 4 s")
        if state["mode"] == "scope":
            raise mcp_client.McpCallError("INSUFFICIENT_SCOPE", "falta incidents:read", 403)
        if state["mode"] == "garbage":
            return {"unexpected": True}
        if name == "incidents_get":
            if arguments["incident_id"] != 3:
                raise mcp_client.McpCallError("NOT_FOUND", "El recurso no existe en TrackFlow.", 404)
            return TICKET
        if name == "incidents_list":
            items = [TICKET] if arguments.get("status") in (None, "in_progress") else []
            return {"total": len(items), "items": items}
        if name == "inventory_list_products":
            items = [PRODUCT] if arguments.get("sku", "").lower() == "tf-box-001" or "carton" in arguments.get("name_contains", "") else []
            return {"total": len(items), "items": items}
        raise AssertionError(name)

    monkeypatch.setattr(mcp_client, "call_tool", fake_call_tool)
    return state


# --------------------------------------------------------------------------- #
# Contratos (sin cambios respecto a la Parte 2)
# --------------------------------------------------------------------------- #
def test_ticket_query_contract_is_typed_and_strict():
    assert tools.TicketQuery(ticket_id=482).ticket_id == 482
    for bad in ({"ticket_id": 0}, {"status": "cerrado"}, {"branch": "Madrid"}, {"priority": "high"}):
        with pytest.raises(ValidationError):
            tools.TicketQuery(**bad)


def test_inventory_query_needs_a_sku_or_a_product_name():
    with pytest.raises(ValidationError):
        tools.InventoryQuery()


# --------------------------------------------------------------------------- #
# Tools del agente → tools MCP
# --------------------------------------------------------------------------- #
def test_ticket_by_id_uses_the_mcp_incidents_get_tool(mcp):
    result = tools.lookup_tickets(tools.TicketQuery(ticket_id=3))

    assert result.status == "ok"
    assert (result.transport, result.mcp_tool) == ("mcp", "incidents_get")
    assert result.records[0]["status"] == "in_progress"
    assert mcp["calls"] == [("incidents_get", {"incident_id": 3})]


def test_ticket_search_uses_incidents_list_with_filters(mcp):
    result = tools.lookup_tickets(tools.TicketQuery(status="in_progress", branch="Zaragoza"))

    assert result.status == "ok" and result.total == 1
    assert mcp["calls"] == [("incidents_list", {"status": "in_progress", "branch": "Zaragoza", "limit": tools.MAX_RESULTS})]


def test_not_found_and_empty_searches_are_not_found(mcp):
    assert tools.lookup_tickets(tools.TicketQuery(ticket_id=999999)).status == "not_found"
    assert tools.lookup_tickets(tools.TicketQuery(status="discarded")).status == "not_found"


@pytest.mark.parametrize("mode", ["down", "scope", "garbage"])
def test_mcp_failures_are_unavailable_and_never_raise(mcp, mode):
    mcp["mode"] = mode
    result = tools.lookup_tickets(tools.TicketQuery(ticket_id=3))
    assert result.status == "unavailable" and result.records == [] and result.error


def test_inventory_uses_the_mcp_inventory_tool(mcp):
    by_sku = tools.lookup_inventory(tools.InventoryQuery(sku="TF-BOX-001"))
    by_name = tools.lookup_inventory(tools.InventoryQuery(product_name="cajas de carton"))

    assert by_sku.records[0]["current_stock"] == 120 and by_name.status == "ok"
    assert [name for name, _ in mcp["calls"]] == ["inventory_list_products", "inventory_list_products"]
    assert tools.lookup_inventory(tools.InventoryQuery(sku="NO-EXISTE")).status == "not_found"


def test_timeout_is_explicit_and_numeric():
    assert tools.TOOL_TIMEOUT_SECONDS == mcp_client.MCP_CALL_TIMEOUT_SECONDS == 4.0


# --------------------------------------------------------------------------- #
# Un solo camino hacia el Incidents Manager
# --------------------------------------------------------------------------- #
def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_agent_has_no_direct_http_path_to_company_services():
    for module in AGENT_DIR.glob("*.py"):
        if module.name == "mcp_client.py":
            continue
        assert not {"httpx", "requests", "urllib"} & imported_modules(module), module.name
    source = "".join(path.read_text(encoding="utf-8") for path in AGENT_DIR.glob("*.py"))
    assert "http_get_json" not in source.replace("`http_get_json`", "")
    assert "AGENT_BACKEND_URL" not in source.replace("`AGENT_BACKEND_URL`", "")
    # httpx en el cliente MCP solo se usa para pedir el token OAuth.
    assert "httpx" not in inspect.getsource(mcp_client.call_tool) + inspect.getsource(mcp_client._acall)


def test_the_agent_only_calls_read_only_mcp_tools(monkeypatch):
    monkeypatch.setattr(mcp_client, "get_agent_token", lambda: pytest.fail("no debe pedir token"))
    for tool_name in ("incidents_create", "incidents_update_status", "inventory_update_stock"):
        with pytest.raises(mcp_client.McpCallError, match="NOT_ALLOWED"):
            mcp_client.call_tool(tool_name, {})


# --------------------------------------------------------------------------- #
# Cliente MCP: token OAuth y lectura de resultados
# --------------------------------------------------------------------------- #
@pytest.fixture
def oauth(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json={"token_endpoint": "https://tenant.logto.test/oidc/token"})
        return httpx.Response(200, json={"access_token": "jwt-del-agente", "expires_in": 3600, "token_type": "Bearer"})

    for name, value in {
        "MCP_AUTH_ISSUER": "https://tenant.logto.test/oidc",
        "MCP_RESOURCE_URL": "https://codespace-8001.app.github.dev/mcp",
        "MCP_AGENT_CLIENT_ID": "agent-app",
        "MCP_AGENT_CLIENT_SECRET": "secreto-de-prueba",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(mcp_client, "OAUTH_TRANSPORT", httpx.MockTransport(handler))
    mcp_client.clear_token_cache()
    yield requests
    mcp_client.clear_token_cache()


def test_agent_token_uses_client_credentials_with_read_only_scopes_and_is_cached(oauth):
    assert mcp_client.get_agent_token() == "jwt-del-agente"
    assert mcp_client.get_agent_token() == "jwt-del-agente"

    token_requests = [r for r in oauth if r.url.path.endswith("/token")]
    assert len(token_requests) == 1  # la segunda vez sale de la caché
    form = dict(httpx.QueryParams(token_requests[0].content.decode()))
    assert form == {
        "grant_type": "client_credentials",
        "resource": "https://codespace-8001.app.github.dev/mcp",
        "scope": "incidents:read inventory:read",
    }
    assert token_requests[0].headers["authorization"].startswith("Basic ")


def test_missing_credentials_make_the_mcp_unavailable(monkeypatch):
    mcp_client.clear_token_cache()
    monkeypatch.setenv("MCP_AGENT_CLIENT_ID", "")
    monkeypatch.setenv("MCP_AGENT_CLIENT_SECRET", "")
    with pytest.raises(mcp_client.McpUnavailable):
        mcp_client.get_agent_token()


def test_slow_mcp_server_is_a_timeout(monkeypatch):
    async def slow(*_):
        await asyncio.sleep(10)

    monkeypatch.setattr(mcp_client, "get_agent_token", lambda: "token")
    monkeypatch.setattr(mcp_client, "MCP_CALL_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(mcp_client, "_acall", slow)
    with pytest.raises(mcp_client.McpUnavailable, match="timeout"):
        mcp_client.call_tool("incidents_get", {"incident_id": 3})


def test_tool_messages_are_parsed_from_structured_content_or_error_json():
    ok = SimpleNamespace(content=[{"type": "text", "text": "{}"}], artifact={"structured_content": TICKET}, status="success")
    assert mcp_client.parse_tool_message(ok) == TICKET

    error_text = "Error: " + json.dumps({"error": {"code": "NOT_FOUND", "status": 404, "message": "No existe"}})
    failed = SimpleNamespace(content=[{"type": "text", "text": error_text}], artifact=None, status="error")
    with pytest.raises(mcp_client.McpCallError) as error:
        mcp_client.parse_tool_message(failed)
    assert (error.value.code, error.value.status) == ("NOT_FOUND", 404)
