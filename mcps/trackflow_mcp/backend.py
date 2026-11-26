"""Cliente HTTP de la API de TrackFlow que usa el servidor MCP.

El servidor MCP **no reimplementa** el Incidents Manager ni el inventario: llama a
sus endpoints. Solo se permiten estas operaciones (lista blanca):

| Método | Ruta | Uso |
|---|---|---|
| GET | `/api/incidents`, `/api/incidents/{id}` | consultar incidencias |
| POST | `/api/incidents` | crear una incidencia |
| PATCH | `/api/incidents/{id}/status` | cambiar el estado (endpoint de ciclo de vida) |
| GET | `/inventory/products`, `/inventory/products/{id}` | consultar el inventario |

Cualquier otra combinación se rechaza antes de salir a la red; en particular,
cualquier escritura sobre `/inventory` da `READ_ONLY_RESOURCE`. Timeout de 5 s.
"""

from __future__ import annotations

import re
from typing import Any

from .config import BACKEND_TIMEOUT_SECONDS
from .errors import McpToolError

ALLOWED_OPERATIONS = (
    ("GET", re.compile(r"^/api/incidents$")),
    ("GET", re.compile(r"^/api/incidents/\d+$")),
    ("POST", re.compile(r"^/api/incidents$")),
    ("PATCH", re.compile(r"^/api/incidents/\d+/status$")),
    ("GET", re.compile(r"^/inventory/products$")),
    ("GET", re.compile(r"^/inventory/products/\d+$")),
)

# Los tests sustituyen el transporte de httpx (httpx.MockTransport).
HTTP_TRANSPORT = None


def check_operation(method: str, path: str) -> None:
    method = method.upper()
    if path.startswith("/inventory") and method != "GET":
        raise McpToolError(
            "READ_ONLY_RESOURCE",
            "El inventario es de solo lectura a través de este servidor MCP: no se permite modificarlo.",
            operation=f"{method} {path}",
        )
    if not any(method == allowed and pattern.match(path) for allowed, pattern in ALLOWED_OPERATIONS):
        raise McpToolError("INTERNAL_ERROR", f"Operación no permitida por el servidor MCP: {method} {path}")


def _detail(response) -> Any:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    return body.get("detail", body) if isinstance(body, dict) else body


SERVICE_KEY_HEADER = "X-Service-Key"
CREDENTIAL_REJECTED = "La API de TrackFlow rechazó la credencial del servidor MCP."


class BackendClient:
    def __init__(self, base_url: str, transport=None, *, service_key: str = ""):
        self.base_url = base_url.rstrip("/")
        self.transport = transport if transport is not None else HTTP_TRANSPORT
        # Identidad de servicio ante la API (D9). Va en cada petición y nunca se registra.
        self._service_key = service_key

    def __repr__(self) -> str:
        return f"BackendClient(base_url={self.base_url!r}, service_key={'***' if self._service_key else None})"

    def request(self, method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any:
        check_operation(method, path)
        import httpx

        try:
            headers = {SERVICE_KEY_HEADER: self._service_key} if self._service_key else None
            with httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(BACKEND_TIMEOUT_SECONDS),
                transport=self.transport,
                headers=headers,
            ) as client:
                response = client.request(method.upper(), path, params=params or None, json=json)
        except httpx.TimeoutException as exc:
            raise McpToolError(
                "UPSTREAM_UNAVAILABLE", f"La API de TrackFlow no respondió en {BACKEND_TIMEOUT_SECONDS:g} s."
            ) from exc
        except httpx.HTTPError as exc:
            raise McpToolError("UPSTREAM_UNAVAILABLE", f"No se pudo conectar con la API de TrackFlow ({type(exc).__name__}).") from exc

        if response.status_code in (401, 403):
            raise McpToolError("UPSTREAM_UNAVAILABLE", CREDENTIAL_REJECTED)
        if response.status_code == 404:
            raise McpToolError("NOT_FOUND", "El recurso no existe en TrackFlow.", path=path)
        if response.status_code == 400 and path.endswith("/status"):
            detail = _detail(response)
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
            raise McpToolError("INVALID_TRANSITION", message or "Transición de estado no permitida.")
        if response.status_code in (400, 422):
            raise McpToolError("VALIDATION_ERROR", "La API de TrackFlow rechazó los datos.", detail=_detail(response))
        if response.status_code >= 400:
            raise McpToolError("UPSTREAM_UNAVAILABLE", f"La API de TrackFlow respondió HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise McpToolError("UPSTREAM_UNAVAILABLE", "La API de TrackFlow devolvió una respuesta no JSON.") from exc
