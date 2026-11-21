"""Catálogo de errores del servidor MCP: un código y un estado distinto para cada causa.

Hay dos niveles:

* **Transporte (HTTP)** — los aplica el middleware de MCP Auth antes de llegar a
  ninguna tool. La respuesta lleva `WWW-Authenticate` con la URL de la
  Protected Resource Metadata.

  | HTTP | `error` (en `WWW-Authenticate` y en el cuerpo) | Cuándo |
  |---|---|---|
  | 401 | `missing_auth_header` | No hay cabecera `Authorization` |
  | 401 | `invalid_auth_header_format` / `missing_bearer_token` | La cabecera no es `Bearer <token>` |
  | 401 | `invalid_token` | Firma no válida, token caducado o mal formado |
  | 401 | `invalid_issuer` | El token no lo emitió el proveedor configurado (`MCP_AUTH_ISSUER`) |
  | 401 | `invalid_audience` | El token se emitió para otro recurso (su `aud` no es `MCP_RESOURCE_URL`) |

* **Tool (MCP `CallToolResult` con `isError: true`)** — el texto es un JSON
  `{"error": {"code", "status", "message", ...}}` con estos códigos:

  | `code` | `status` | Cuándo |
  |---|---|---|
  | `INSUFFICIENT_SCOPE` | 403 | El token es válido pero no tiene el scope que exige la tool |
  | `READ_ONLY_RESOURCE` | 403 | Intento de modificar el inventario (siempre se rechaza) |
  | `VALIDATION_ERROR` | 422 | Argumentos que no cumplen el esquema de la tool |
  | `NOT_FOUND` | 404 | La incidencia o el producto no existe |
  | `INVALID_TRANSITION` | 409 | El Incidents Manager rechaza el cambio de estado (ciclo de vida) |
  | `UPSTREAM_UNAVAILABLE` | 503 | La API de TrackFlow no responde o falla |
  | `UNKNOWN_TOOL` | 404 | La tool pedida no existe |
  | `INTERNAL_ERROR` | 500 | Error no previsto del servidor |
"""

from __future__ import annotations

import json
from typing import Any

ERROR_STATUS = {
    "INSUFFICIENT_SCOPE": 403,
    "READ_ONLY_RESOURCE": 403,
    "VALIDATION_ERROR": 422,
    "NOT_FOUND": 404,
    "INVALID_TRANSITION": 409,
    "UPSTREAM_UNAVAILABLE": 503,
    "UNKNOWN_TOOL": 404,
    "INTERNAL_ERROR": 500,
}


class McpToolError(Exception):
    """Error de negocio de una tool, con código estable para el cliente."""

    def __init__(self, code: str, message: str, **details: Any):
        if code not in ERROR_STATUS:
            raise ValueError(f"Código de error desconocido: {code}")
        super().__init__(message)
        self.code = code
        self.status = ERROR_STATUS[code]
        self.message = message
        self.details = {key: value for key, value in details.items() if value is not None}

    def to_payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "status": self.status, "message": self.message, **self.details}}

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False)
