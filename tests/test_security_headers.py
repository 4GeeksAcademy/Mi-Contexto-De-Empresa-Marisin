"""Cabeceras de seguridad de la API (auditoría OWASP · H2, D15).

    python -m pytest tests/test_security_headers.py
"""

import pytest
from fastapi.testclient import TestClient

from services.api.main import app

EXPECTED = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
    "cross-origin-opener-policy": "same-origin",
}
HSTS = "max-age=31536000; includeSubDomains"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize(
    "method, path",
    [("GET", "/auth/me"), ("GET", "/ruta-que-no-existe"), ("POST", "/auth/login"), ("GET", "/openapi.json")],
)
def test_every_response_carries_the_security_headers(client, method, path):
    response = client.request(method, path, json={} if method == "POST" else None)

    for name, value in EXPECTED.items():
        assert response.headers.get(name) == value, name


def test_cors_preflight_also_carries_them(client):
    response = client.options("/auth/login", headers={
        "Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"})
    assert response.headers.get("x-frame-options") == "DENY"


def test_no_hsts_over_plain_http(client):
    assert "strict-transport-security" not in client.get("/auth/me").headers


def test_hsts_behind_a_tls_proxy(client):
    response = client.get("/auth/me", headers={"X-Forwarded-Proto": "https"})
    assert response.headers.get("strict-transport-security") == HSTS


def test_hsts_over_direct_https():
    response = TestClient(app, base_url="https://testserver").get("/auth/me")
    assert response.headers.get("strict-transport-security") == HSTS


def test_no_csp_on_the_api(client):
    """La API sirve JSON y /docs; la CSP se recomienda en los frontends (informe)."""
    assert "content-security-policy" not in client.get("/auth/me").headers
