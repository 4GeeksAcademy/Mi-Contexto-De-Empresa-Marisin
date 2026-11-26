"""Configuración del servidor MCP, leída del entorno (`.env` de la raíz del monorepo).

| Variable | Para qué | Ejemplo |
|---|---|---|
| `MCP_AUTH_ISSUER` | Issuer OIDC del proveedor OAuth (Logto) | `https://abc123.logto.app/oidc` |
| `MCP_RESOURCE_URL` | Identificador del recurso protegido = `aud` esperado del token = URL pública del endpoint MCP | `https://<codespace>-8001.app.github.dev/mcp` |
| `TRACKFLOW_API_URL` | API de TrackFlow (Incidents Manager e inventario) | `http://localhost:8000` |
| `MCP_PORT` | Puerto del servidor MCP | `8001` |
| `MCP_AUDIT_LOG` | Fichero JSONL del log de invocaciones | `logs/mcp-tool-calls.jsonl` |
| `MCP_ALLOWED_ORIGINS` | Orígenes CORS permitidos (coma), para clientes de navegador como MCP Playground | `*` |
| `TRACKFLOW_SERVICE_KEY` | Clave de servicio con la que el MCP se identifica ante la API (`X-Service-Key`, ≥ 32 caracteres) | — (solo en `.env`) |

Nunca hay secretos en el código. Los tokens de los clientes se validan con las claves
públicas JWKS del proveedor; la única credencial propia es `TRACKFLOW_SERVICE_KEY`, que
se lee del entorno, no aparece en el `repr` de `Settings` y nunca se registra.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Scopes que el servidor reconoce. No existe ningún scope de escritura de inventario.
SCOPE_INCIDENTS_READ = "incidents:read"
SCOPE_INCIDENTS_WRITE = "incidents:write"
SCOPE_INVENTORY_READ = "inventory:read"
SCOPES_SUPPORTED = (SCOPE_INCIDENTS_READ, SCOPE_INCIDENTS_WRITE, SCOPE_INVENTORY_READ)

BACKEND_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class Settings:
    auth_issuer: str
    resource_url: str
    api_url: str
    port: int
    audit_log: Path
    allowed_origins: tuple[str, ...]
    service_key: str = field(default="", repr=False)


def load_settings() -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # pragma: no cover - python-dotenv es dependencia del monorepo
        pass
    origins = os.environ.get("MCP_ALLOWED_ORIGINS", "*")
    return Settings(
        auth_issuer=os.environ.get("MCP_AUTH_ISSUER", "").strip().rstrip("/"),
        resource_url=os.environ.get("MCP_RESOURCE_URL", "http://localhost:8001/mcp").strip(),
        api_url=(os.environ.get("TRACKFLOW_API_URL") or "http://localhost:8000").strip().rstrip("/"),
        port=int(os.environ.get("MCP_PORT", "8001")),
        audit_log=Path(os.environ.get("MCP_AUDIT_LOG") or ROOT / "logs" / "mcp-tool-calls.jsonl"),
        allowed_origins=tuple(origin.strip() for origin in origins.split(",") if origin.strip()),
        service_key=os.environ.get("TRACKFLOW_SERVICE_KEY", "").strip(),
    )
