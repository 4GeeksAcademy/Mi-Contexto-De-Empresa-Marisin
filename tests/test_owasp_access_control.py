"""Matriz de control de acceso de la API (OWASP A01: C1, C4 · D8, D9, D19).

Cada una de las **53** operaciones HTTP tiene su política en `POLICY`. Una ruta nueva sin
política hace fallar `test_every_route_has_a_policy`, así que nadie puede añadir un endpoint
sin decidir quién lo usa.

Las políticas:

* `public`            sin token (login, recuperación de contraseña, registro, ingesta de telemetría);
* `authenticated`     cualquier usuario con sesión, también un cliente (`user`); si hay control de
                      propiedad (dueño o admin), lo hace la propia función;
* `staff`             solo personal de TrackFlow (`admin`/`manager`): un `user` recibe 403;
* `staff_or_service`  staff o el servidor MCP con `X-Service-Key` válida.

Cómo se prueba sin efectos secundarios:

* **Contra la app real**, solo las peticiones que se rechazan en la puerta de autorización,
  antes de que se ejecute el endpoint: sin token → 401; `user` en rutas staff → 403; una
  `X-Service-Key` falsa → 401. Las rutas públicas son todas `POST`: sin cuerpo dan 422.
* **Contra una app espejo** que monta cada ruta con **las mismas dependencias de
  autorización** y un endpoint vacío: `manager` pasa (no 401/403), la clave de servicio válida
  solo abre `staff_or_service` y un `user` pasa en las rutas `authenticated`. Así no se lanza el
  stream SSE, ni Celery, ni la base de datos real, ni un `DELETE` sobre el TinyDB local.
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from services.api import security
from services.api.main import app
from services.api.security import (
    SERVICE_KEY_ENV,
    SERVICE_KEY_HEADER,
    STAFF_ONLY_DETAIL,
    create_access_token,
    get_current_user,
    require_staff,
    require_staff_or_service,
)
from services.api.routes import users as user_routes
from services.api.services import users as user_service
from tests.test_serialization_contracts import _api_routes

EXPECTED_OPERATIONS = 53
SERVICE_KEY = "test-service-key-" + "x" * 32
FIXED_UUID = "00000000-0000-0000-0000-000000000001"

USERS = {
    1: {"id": 1, "email": "cliente@example.com", "role": "user", "is_active": True},
    2: {"id": 2, "email": "manager@example.com", "role": "manager", "is_active": True},
    3: {"id": 3, "email": "admin@example.com", "role": "admin", "is_active": True},
}
USER_ID, MANAGER_ID, ADMIN_ID = 1, 2, 3

PUBLIC = "public"
AUTHENTICATED = "authenticated"
STAFF = "staff"
STAFF_OR_SERVICE = "staff_or_service"

POLICY: dict[tuple[str, str], str] = {
    # Públicas
    ("POST", "/auth/login"): PUBLIC,
    ("POST", "/auth/forgot-password"): PUBLIC,
    ("POST", "/auth/reset-password"): PUBLIC,
    ("POST", "/users"): PUBLIC,
    ("POST", "/telemetry/events"): PUBLIC,
    # Cualquier autenticado (cuenta propia, chat y agente)
    ("GET", "/auth/me"): AUTHENTICATED,
    ("POST", "/auth/change-password"): AUTHENTICATED,
    ("GET", "/profiles/me"): AUTHENTICATED,
    ("PUT", "/profiles/me"): AUTHENTICATED,
    ("GET", "/profiles/{profile_id}"): AUTHENTICATED,  # dueño o admin (en la función)
    ("GET", "/users/{user_id}"): AUTHENTICATED,  # el propio usuario o staff (en la función)
    ("PUT", "/users/{user_id}"): AUTHENTICATED,  # dueño o admin (en la función)
    ("DELETE", "/users/{user_id}"): AUTHENTICATED,  # dueño o admin (en la función)
    ("POST", "/agent/query"): AUTHENTICATED,
    ("POST", "/agent/chat/sessions"): AUTHENTICATED,
    # Personal de TrackFlow
    ("GET", "/users"): STAFF,
    ("GET", "/agent/traces/{run_id}"): STAFF,
    ("GET", "/agent/memory"): STAFF,
    ("GET", "/agent/memory/audit"): STAFF,
    ("GET", "/agent/guardrails/summary"): STAFF,
    ("GET", "/suppliers"): STAFF,
    ("POST", "/suppliers"): STAFF,
    ("GET", "/suppliers/{supplier_id}"): STAFF,
    ("DELETE", "/suppliers/{supplier_id}"): STAFF,
    ("PATCH", "/suppliers/{supplier_id}/rate"): STAFF,
    ("PATCH", "/suppliers/{supplier_id}/status"): STAFF,
    ("POST", "/inventory/products"): STAFF,
    ("PATCH", "/inventory/products/{product_id}/stock"): STAFF,
    ("POST", "/inventory/orders/inbound"): STAFF,
    ("POST", "/inventory/orders/outbound"): STAFF,
    ("GET", "/inventory/orders"): STAFF,
    ("GET", "/rfp/tickets"): STAFF,
    ("POST", "/rfp/tickets"): STAFF,
    ("GET", "/rfp/tickets/{ticket_id}"): STAFF,
    ("POST", "/rfp/tickets/{ticket_id}/drafts"): STAFF,
    ("POST", "/rfp/tickets/{ticket_id}/approvals"): STAFF,
    ("POST", "/rfp/tickets/{ticket_id}/approvals/{department_id}"): STAFF,
    ("GET", "/rfp/tickets/{ticket_id}/trace"): STAFF,
    ("GET", "/rfp/tickets/{ticket_id}/document"): STAFF,
    ("GET", "/reporting/pipeline-runs/latest"): STAFF,
    ("POST", "/reporting/pipeline-runs"): STAFF,
    ("GET", "/reporting/weekly-warehouse-client-performance"): STAFF,
    ("POST", "/knowledge/query"): STAFF,
    ("GET", "/realtime/events"): STAFF,
    ("GET", "/tasks/{task_id}"): STAFF,
    ("GET", "/telemetry/report"): STAFF,
    # Staff o el servidor MCP (lo que permite la lista blanca del MCP)
    ("GET", "/api/incidents"): STAFF_OR_SERVICE,
    ("POST", "/api/incidents"): STAFF_OR_SERVICE,
    ("GET", "/api/incidents/summary"): STAFF_OR_SERVICE,
    ("GET", "/api/incidents/{incident_id}"): STAFF_OR_SERVICE,
    ("PATCH", "/api/incidents/{incident_id}/status"): STAFF_OR_SERVICE,
    ("GET", "/inventory/products"): STAFF_OR_SERVICE,
    ("GET", "/inventory/products/{product_id}"): STAFF_OR_SERVICE,
}

# Una ruta representativa por router de D8: el 403 lleva el mensaje común.
STAFF_ROUTER_SAMPLES = [
    ("GET", "/users"),
    ("GET", "/suppliers"),
    ("GET", "/rfp/tickets"),
    ("GET", "/reporting/pipeline-runs/latest"),
    ("POST", "/knowledge/query"),
    ("GET", "/realtime/events"),
    ("GET", "/tasks/{task_id}"),
    ("GET", "/telemetry/report"),
    ("GET", "/inventory/orders"),
    ("GET", "/api/incidents"),
    ("GET", "/inventory/products"),
]


# --------------------------------------------------------------------------- #
# Descubrimiento de rutas (el mismo recorrido que `_api_routes`, conservando el prefijo)
# --------------------------------------------------------------------------- #
def _routes_with_full_path(routes, prefix: str = ""):
    """Como `_api_routes`, pero devuelve la ruta completa: en FastAPI 0.141 un router incluido
    dentro de otro (el chat dentro de `/agent`) no lleva el prefijo del padre en `route.path`;
    ese prefijo está en el `include_context` del router incluido."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue
        nested_router = getattr(route, "original_router", None)
        if nested_router is not None:
            context = getattr(route, "include_context", None)
            yield from _routes_with_full_path(nested_router.routes, prefix + (getattr(context, "prefix", "") or ""))
        else:
            yield from _routes_with_full_path(getattr(route, "routes", ()), prefix)


def _operations():
    operations = {}
    for path, route in _routes_with_full_path(app.routes):
        if not route.include_in_schema:
            continue
        for method in route.methods:
            operations[(method, path)] = route
    return operations


OPERATIONS = _operations()


def _concrete(path: str, route: APIRoute) -> str:
    uuid_params = {p.name for p in route.dependant.path_params if p.field_info.annotation is UUID}

    def fill(match: re.Match) -> str:
        return FIXED_UUID if match.group(1) in uuid_params else "1"

    return re.sub(r"\{([^}:]+)(?::[^}]+)?\}", fill, path)


def _cases(*policies: str):
    return [
        pytest.param(method, path, id=f"{method} {path}")
        for (method, path), policy in sorted(POLICY.items())
        if policy in policies
    ]


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def known_users(monkeypatch):
    # Nunca el TinyDB local: la sesión (security) y la ruta de usuarios leen de aquí.
    monkeypatch.setattr(user_service, "get_user_by_id", lambda user_id: USERS.get(user_id))
    monkeypatch.setattr(user_routes, "get_user_by_id", lambda user_id: USERS.get(user_id))
    monkeypatch.setenv(SERVICE_KEY_ENV, SERVICE_KEY)


def _bearer(user_id: int) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


@pytest.fixture
def client():
    # Sin `with`: no se ejecuta el startup (no siembra ni toca el TinyDB local).
    test_client = TestClient(app)
    yield test_client
    test_client.close()


def _call(client: TestClient, method: str, path: str, headers: dict | None = None):
    return client.request(method, _concrete(path, OPERATIONS[(method, path)]), headers=headers or {})


GATES = {get_current_user, require_staff, require_staff_or_service}


def _auth_gates(route: APIRoute):
    """Las dependencias de autorización de la ruta (incluidas las del router)."""
    return [dep.call for dep in route.dependant.dependencies if dep.call in GATES]


@pytest.fixture
def mirror():
    """App espejo: cada ruta con sus mismas puertas de autorización y un endpoint vacío."""
    probe = FastAPI()
    for (method, path), route in OPERATIONS.items():
        probe.add_api_route(
            path,
            lambda: {"ok": True},
            methods=[method],
            dependencies=[Depends(gate) for gate in _auth_gates(route)],
            name=f"{method} {path}",
        )
    with TestClient(probe) as test_client:
        yield test_client


# --------------------------------------------------------------------------- #
# Inventario: 53 operaciones, todas con política
# --------------------------------------------------------------------------- #
def test_route_walk_matches_api_routes_and_finds_53_operations():
    via_api_routes = sum(len(r.methods) for r in _api_routes(app.routes) if r.include_in_schema)
    assert via_api_routes == EXPECTED_OPERATIONS
    assert len(OPERATIONS) == EXPECTED_OPERATIONS


def test_full_paths_match_the_openapi_contract():
    openapi = {(m.upper(), p) for p, item in app.openapi()["paths"].items() for m in item}
    assert set(OPERATIONS) == openapi


def test_every_route_has_a_policy():
    missing = sorted(set(OPERATIONS) - set(POLICY))
    stale = sorted(set(POLICY) - set(OPERATIONS))
    assert not missing, f"rutas sin política de acceso: {missing}"
    assert not stale, f"políticas de rutas que ya no existen: {stale}"
    assert len(POLICY) == EXPECTED_OPERATIONS


def test_every_protected_route_has_an_auth_gate():
    for key, policy in POLICY.items():
        gates = _auth_gates(OPERATIONS[key])
        if policy == PUBLIC:
            assert gates == [], key
        else:
            assert gates, f"{key} no tiene ninguna dependencia de autorización"


def test_public_routes_are_only_posts_that_need_a_body():
    # Por eso la matriz puede llamarlas sin token sin ejecutar nada (sin cuerpo → 422).
    assert {method for (method, _), policy in POLICY.items() if policy == PUBLIC} == {"POST"}


# --------------------------------------------------------------------------- #
# App real: rechazos en la puerta
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method,path", _cases(AUTHENTICATED, STAFF, STAFF_OR_SERVICE))
def test_without_token_is_401(client, method, path):
    assert _call(client, method, path).status_code == 401


@pytest.mark.parametrize("method,path", _cases(PUBLIC))
def test_public_routes_do_not_ask_for_a_token(client, method, path):
    assert _call(client, method, path).status_code not in (401, 403)


@pytest.mark.parametrize("method,path", _cases(STAFF, STAFF_OR_SERVICE))
def test_customer_account_is_403_on_internal_routes(client, method, path):
    assert _call(client, method, path, _bearer(USER_ID)).status_code == 403


@pytest.mark.parametrize("method,path", [pytest.param(m, p, id=f"{m} {p}") for m, p in STAFF_ROUTER_SAMPLES])
def test_each_internal_router_explains_the_403(client, method, path):
    response = _call(client, method, path, _bearer(USER_ID))
    assert response.status_code == 403
    assert response.json() == {"detail": STAFF_ONLY_DETAIL}


@pytest.mark.parametrize("method,path", _cases(STAFF_OR_SERVICE))
def test_invalid_service_key_is_401(client, method, path):
    assert _call(client, method, path, {SERVICE_KEY_HEADER: "falsa-" + "y" * 40}).status_code == 401


@pytest.mark.parametrize("method,path", _cases(STAFF_OR_SERVICE))
def test_invalid_service_key_is_401_even_with_a_staff_token(client, method, path):
    headers = {**_bearer(MANAGER_ID), SERVICE_KEY_HEADER: "falsa-" + "y" * 40}
    assert _call(client, method, path, headers).status_code == 401


def test_a_customer_cannot_read_another_user(client):
    assert client.get(f"/users/{MANAGER_ID}", headers=_bearer(USER_ID)).status_code == 403
    own = client.get(f"/users/{USER_ID}", headers=_bearer(USER_ID))
    assert own.status_code == 200 and own.json()["email"] == USERS[USER_ID]["email"]
    assert client.get(f"/users/{USER_ID}", headers=_bearer(MANAGER_ID)).status_code == 200


# --------------------------------------------------------------------------- #
# App espejo: quién pasa la puerta
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method,path", _cases(AUTHENTICATED, STAFF, STAFF_OR_SERVICE))
@pytest.mark.parametrize("staff_id", [MANAGER_ID, ADMIN_ID], ids=["manager", "admin"])
def test_staff_passes_every_gate(mirror, method, path, staff_id):
    assert mirror.request(method, path, headers=_bearer(staff_id)).status_code == 200


@pytest.mark.parametrize("method,path", _cases(AUTHENTICATED))
def test_customer_passes_the_authenticated_gate(mirror, method, path):
    assert mirror.request(method, path, headers=_bearer(USER_ID)).status_code == 200


@pytest.mark.parametrize("method,path", _cases(STAFF_OR_SERVICE))
def test_valid_service_key_opens_only_incidents_and_product_reads(mirror, method, path):
    assert mirror.request(method, path, headers={SERVICE_KEY_HEADER: SERVICE_KEY}).status_code == 200


@pytest.mark.parametrize("method,path", _cases(AUTHENTICATED, STAFF))
def test_valid_service_key_does_not_open_anything_else(mirror, method, path):
    assert mirror.request(method, path, headers={SERVICE_KEY_HEADER: SERVICE_KEY}).status_code == 401


@pytest.mark.parametrize("short_key", ["", "corta"])
def test_service_path_is_disabled_without_a_long_enough_key(mirror, monkeypatch, short_key):
    monkeypatch.setenv(SERVICE_KEY_ENV, short_key)
    assert security.configured_service_key() is None
    assert mirror.get("/api/incidents", headers={SERVICE_KEY_HEADER: short_key or "x"}).status_code == 401


def test_service_identity_is_not_a_user():
    identity = require_staff_or_service(token=None, service_key=SERVICE_KEY)
    assert identity == {"id": 0, "role": "service", "service": "trackflow-mcp"}


def test_missing_service_key_is_reported_at_startup(monkeypatch, caplog):
    monkeypatch.delenv(SERVICE_KEY_ENV, raising=False)
    with caplog.at_level("WARNING", logger="api.security"):
        security.warn_if_service_key_missing()
    assert "vía de servicio del MCP está desactivada" in caplog.text
    assert SERVICE_KEY not in caplog.text
