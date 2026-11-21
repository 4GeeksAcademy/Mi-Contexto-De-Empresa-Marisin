"""Pruebas del servidor MCP de TrackFlow (`mcps/trackflow_mcp`), sin red ni proveedor OAuth real.

* Lógica y permisos de las tools con la API simulada (`httpx.MockTransport`).
* Discovery: nombres, descripciones, esquemas y anotaciones vía `list_tools()`.
* Errores codificados y log de auditoría en cada invocación.
* OAuth (MCP Auth): Protected Resource Metadata, 401 sin token / token inválido /
  audiencia incorrecta, y acceso con un token válido. La verificación del JWT se
  sustituye por una función que mapea tokens de prueba a su `AuthInfo`.

    python -m pytest tests/mcps
"""

import asyncio
import json

import httpx
import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcpauth.config import AuthorizationServerMetadata, AuthServerConfig, AuthServerType
from mcpauth.exceptions import MCPAuthTokenVerificationException, MCPAuthTokenVerificationExceptionCode
from mcpauth.types import AuthInfo
from starlette.testclient import TestClient

from mcps.trackflow_mcp import backend as backend_module
from mcps.trackflow_mcp.audit import AuditLog
from mcps.trackflow_mcp.backend import BackendClient
from mcps.trackflow_mcp.config import Settings
from mcps.trackflow_mcp.errors import McpToolError
from mcps.trackflow_mcp.server import build_mcp, create_app
from mcps.trackflow_mcp.service import TOOL_POLICIES, Caller, TrackFlowTools

ISSUER = "https://tenant.logto.test/oidc"
RESOURCE = "https://codespace-8001.app.github.dev/mcp"
FULL = Caller("admin-app", "admin-app", ["incidents:read", "incidents:write", "inventory:read"])
READ_ONLY = Caller("agent-app", "agent-app", ["incidents:read", "inventory:read"])
INCIDENT = {
    "id": "1", "title": "Caja aplastada", "description": "Lateral hundido", "category": "DAMAGE",
    "status": "open", "origin": "customer", "branch": "Zaragoza",
    "created_at": "2026-11-21T17:52:08+00:00", "updated_at": "2026-11-21T17:53:35+00:00",
}
PRODUCTS = [
    {"id": 1, "sku": "TF-TEE-001", "name": "Camiseta técnica", "client_name": "RunCo", "category": "Apparel", "reference": "R1", "current_stock": 40},
    {"id": 2, "sku": "LOAD-0001", "name": "Carga sintética", "client_name": "X", "category": "Home", "reference": "R2", "current_stock": 9},
]


# --------------------------------------------------------------------------- #
# API de TrackFlow simulada
# --------------------------------------------------------------------------- #
@pytest.fixture
def api():
    state = {"requests": [], "down": False, "incidents": {"1": dict(INCIDENT)}}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append((request.method, request.url.path, request.content))
        if state["down"]:
            raise httpx.ConnectError("caído", request=request)
        path, method = request.url.path, request.method
        if path == "/api/incidents" and method == "GET":
            return httpx.Response(200, json=list(state["incidents"].values()))
        if path == "/api/incidents" and method == "POST":
            body = json.loads(request.content)
            created = {**body, "id": "2", "status": "open", "created_at": "2026-11-21T18:00:00+00:00", "updated_at": "2026-11-21T18:00:00+00:00"}
            state["incidents"]["2"] = created
            return httpx.Response(201, json=created)
        if path.endswith("/status") and method == "PATCH":
            incident = state["incidents"].get(path.split("/")[3])
            if incident is None:
                return httpx.Response(404, json={"detail": "La incidencia no existe"})
            target = json.loads(request.content)["status"]
            if (incident["status"], target) not in {("open", "in_progress"), ("open", "discarded"), ("in_progress", "resolved"), ("in_progress", "discarded")}:
                return httpx.Response(400, json={"detail": {"field": "status", "message": f"No se puede cambiar de {incident['status']} a {target}"}})
            incident["status"] = target
            return httpx.Response(200, json=incident)
        if path.startswith("/api/incidents/") and method == "GET":
            incident = state["incidents"].get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=incident) if incident else httpx.Response(404, json={"detail": "La incidencia no existe"})
        if path == "/inventory/products" and method == "GET":
            return httpx.Response(200, json=PRODUCTS)
        return httpx.Response(405)

    state["backend"] = BackendClient("http://api.test", transport=httpx.MockTransport(handler))
    state["tools"] = TrackFlowTools(state["backend"])
    return state


def methods(api):
    return [(method, path) for method, path, _ in api["requests"]]


# --------------------------------------------------------------------------- #
# Tools: Incidents Manager real y ciclo de vida
# --------------------------------------------------------------------------- #
def test_incident_tools_read_create_and_update_through_the_incidents_manager(api):
    tools = api["tools"]
    assert tools.incidents_get(READ_ONLY, incident_id=1).allowed_next_statuses == ["in_progress", "discarded"]
    created = tools.incidents_create(FULL, title="Paquete perdido", description="Sin tracking", category="LOST_PARCEL", origin="internal", branch="Zaragoza")
    updated = tools.incidents_update_status(FULL, incident_id=1, status="in_progress")

    assert created.status.value == "open"
    assert updated.status.value == "in_progress"
    assert methods(api) == [
        ("GET", "/api/incidents/1"),
        ("POST", "/api/incidents"),
        ("PATCH", "/api/incidents/1/status"),  # endpoint de ciclo de vida, no un PATCH genérico
    ]


def test_invalid_lifecycle_transition_is_its_own_error(api):
    with pytest.raises(McpToolError) as error:
        api["tools"].incidents_update_status(FULL, incident_id=1, status="resolved")
    assert (error.value.code, error.value.status) == ("INVALID_TRANSITION", 409)
    assert "open a resolved" in error.value.message


def test_missing_incident_and_service_down_have_distinct_codes(api):
    with pytest.raises(McpToolError) as missing:
        api["tools"].incidents_get(READ_ONLY, incident_id=99)
    api["down"] = True
    with pytest.raises(McpToolError) as down:
        api["tools"].incidents_get(READ_ONLY, incident_id=1)
    assert missing.value.code == "NOT_FOUND" and down.value.code == "UPSTREAM_UNAVAILABLE"


# --------------------------------------------------------------------------- #
# Mínimo privilegio y solo lectura del inventario
# --------------------------------------------------------------------------- #
def test_every_tool_declares_its_policy_and_no_inventory_write_scope_exists():
    assert {policy.scope for policy in TOOL_POLICIES.values()} == {"incidents:read", "incidents:write", "inventory:read", None}
    assert all(policy.access != "write" for policy in TOOL_POLICIES.values() if policy.resource == "inventory")


def test_a_read_only_token_cannot_write_incidents(api):
    with pytest.raises(McpToolError) as error:
        api["tools"].incidents_update_status(READ_ONLY, incident_id=1, status="in_progress")
    assert error.value.code == "INSUFFICIENT_SCOPE" and error.value.status == 403
    assert error.value.details["required_scope"] == "incidents:write"
    assert methods(api) == []  # se rechaza antes de llegar a la API


def test_inventory_write_is_explicitly_rejected_even_with_every_scope(api):
    with pytest.raises(McpToolError) as error:
        api["tools"].inventory_update_stock(FULL, product_id=1, new_stock=0)
    assert error.value.code == "READ_ONLY_RESOURCE" and error.value.status == 403
    assert methods(api) == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_backend_client_refuses_any_inventory_write(method):
    with pytest.raises(McpToolError) as error:
        backend_module.check_operation(method, "/inventory/products/1")
    assert error.value.code == "READ_ONLY_RESOURCE"


def test_inventory_query_filters_by_sku_or_name(api):
    tools = api["tools"]
    assert [p.sku for p in tools.inventory_list_products(READ_ONLY, sku="tf-tee-001").items] == ["TF-TEE-001"]
    assert tools.inventory_list_products(READ_ONLY, name_contains="tecnica").total == 1


# --------------------------------------------------------------------------- #
# Discovery, errores codificados y log de auditoría
# --------------------------------------------------------------------------- #
@pytest.fixture
def server(api, tmp_path):
    caller = {"value": FULL}
    mcp = build_mcp(api["tools"], AuditLog(tmp_path / "audit.jsonl"), lambda: caller["value"])
    return {"mcp": mcp, "caller": caller, "log": tmp_path / "audit.jsonl"}


def call(server, name, arguments):
    return asyncio.run(server["mcp"].call_tool(name, arguments))


def error_of(server, name, arguments):
    with pytest.raises(ToolError) as raised:
        call(server, name, arguments)
    return json.loads(str(raised.value))["error"]


def test_discovery_describes_every_tool_with_schemas_and_annotations(server):
    listed = {tool.name: tool for tool in asyncio.run(server["mcp"].list_tools())}

    assert set(listed) == set(TOOL_POLICIES)
    for name, tool in listed.items():
        assert tool.title and len(tool.description) > 60
        policy = TOOL_POLICIES[name]
        assert (policy.scope or "READ_ONLY_RESOURCE") in tool.description
        assert tool.inputSchema["type"] == "object"
    for name in ("incidents_list", "incidents_get", "inventory_list_products", "inventory_get_product"):
        assert listed[name].annotations.readOnlyHint is True
        assert listed[name].outputSchema is not None
    assert listed["inventory_update_stock"].annotations.destructiveHint is True
    status_schema = json.dumps(listed["incidents_update_status"].inputSchema)
    for value in ("open", "in_progress", "resolved", "discarded"):
        assert value in status_schema
    assert "Los Angeles" in json.dumps(listed["incidents_create"].inputSchema)


def test_successful_call_returns_structured_output_and_is_logged(server):
    call(server, "incidents_get", {"incident_id": 1})

    entry = json.loads(server["log"].read_text(encoding="utf-8").splitlines()[-1])
    assert (entry["tool"], entry["client_id"], entry["result"], entry["status"]) == ("incidents_get", "admin-app", "ok", 200)
    assert entry["argument_names"] == ["incident_id"]


def test_auth_validation_and_read_only_errors_have_distinct_codes(server):
    server["caller"]["value"] = READ_ONLY
    scope = error_of(server, "incidents_create", {"title": "x", "description": "y", "category": "DAMAGE", "origin": "customer", "branch": "Zaragoza"})
    read_only = error_of(server, "inventory_update_stock", {"product_id": 1, "new_stock": 0})
    validation = error_of(server, "incidents_list", {"status": "cerrado"})
    unknown = error_of(server, "incidents_delete", {"incident_id": 1})

    assert [(e["code"], e["status"]) for e in (scope, read_only, validation, unknown)] == [
        ("INSUFFICIENT_SCOPE", 403), ("READ_ONLY_RESOURCE", 403), ("VALIDATION_ERROR", 422), ("UNKNOWN_TOOL", 404),
    ]
    assert validation["errors"][0]["field"] == "status"
    results = [json.loads(line)["result"] for line in server["log"].read_text(encoding="utf-8").splitlines()]
    assert results == ["INSUFFICIENT_SCOPE", "READ_ONLY_RESOURCE", "VALIDATION_ERROR", "UNKNOWN_TOOL"]


# --------------------------------------------------------------------------- #
# OAuth con MCP Auth (HTTP)
# --------------------------------------------------------------------------- #
TOKENS = {
    "token-admin": AuthInfo(token="token-admin", issuer=ISSUER, client_id="admin-app", subject="admin-app", audience=RESOURCE, scopes=FULL.scopes, claims={}),
    "token-other-api": AuthInfo(token="token-other-api", issuer=ISSUER, client_id="x", subject="x", audience="https://otra.api", scopes=FULL.scopes, claims={}),
}


def fake_verify(token: str) -> AuthInfo:
    if token not in TOKENS:
        raise MCPAuthTokenVerificationException(MCPAuthTokenVerificationExceptionCode.INVALID_TOKEN)
    return TOKENS[token]


@pytest.fixture
def http(api, tmp_path):
    settings = Settings(
        auth_issuer=ISSUER, resource_url=RESOURCE, api_url="http://api.test", port=8001,
        audit_log=tmp_path / "audit.jsonl", allowed_origins=("*",),
    )
    provider = AuthServerConfig(
        type=AuthServerType.OIDC,
        metadata=AuthorizationServerMetadata(
            issuer=ISSUER,
            authorization_endpoint=f"{ISSUER}/auth",
            token_endpoint=f"{ISSUER}/token",
            jwks_uri=f"{ISSUER}/jwks",
            response_types_supported=["code"],
            grant_types_supported=["authorization_code", "client_credentials"],
            code_challenge_methods_supported=["S256"],
        ),
    )
    app = create_app(settings, auth_server_config=provider, verify=fake_verify, backend=api["backend"])
    with TestClient(app) as client:
        yield client


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


def rpc_result(response):
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])
    return response.json()


def test_protected_resource_metadata_is_public(http):
    metadata = http.get("/.well-known/oauth-protected-resource/mcp").json()
    assert metadata["resource"] == RESOURCE
    assert metadata["scopes_supported"] == ["incidents:read", "incidents:write", "inventory:read"]
    assert ISSUER in json.dumps(metadata["authorization_servers"])


@pytest.mark.parametrize(
    "headers, error",
    [({}, "missing_auth_header"), ({"Authorization": "Basic abc"}, "invalid_auth_header_format"),
     ({"Authorization": "Bearer token-falso"}, "invalid_token"), ({"Authorization": "Bearer token-other-api"}, "invalid_audience")],
)
def test_without_a_valid_token_no_client_can_list_tools(http, headers, error):
    response = http.post("/mcp", headers={**MCP_HEADERS, **headers}, json=LIST_TOOLS)
    assert response.status_code == 401
    challenge = response.headers["www-authenticate"]
    assert f'error="{error}"' in challenge
    assert "/.well-known/oauth-protected-resource/mcp" in challenge


def test_with_a_valid_token_the_client_discovers_the_tools(http):
    response = http.post("/mcp", headers={**MCP_HEADERS, "Authorization": "Bearer token-admin"}, json=LIST_TOOLS)
    assert response.status_code == 200
    names = {tool["name"] for tool in rpc_result(response)["result"]["tools"]}
    assert names == set(TOOL_POLICIES)
