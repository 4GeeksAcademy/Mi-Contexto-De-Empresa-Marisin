"""Cliente MCP del agente: única vía del agente hacia el Incidents Manager y el inventario.

El agente ya no llama a la API de TrackFlow: carga las tools del servidor MCP
(`mcps/trackflow_mcp`) con `langchain-mcp-adapters` (`MultiServerMCPClient`,
transporte Streamable HTTP) y las invoca autenticándose con OAuth:

1. Obtiene un access token con `client_credentials` en el proveedor (Logto) con
   la app `trackflow-agent`, que solo tiene `incidents:read` e `inventory:read`
   (mínimo privilegio: el agente no puede crear ni cambiar incidencias). El token
   se guarda en memoria hasta un minuto antes de caducar.
2. Abre una sesión MCP en `MCP_SERVER_URL` con `Authorization: Bearer <token>`,
   carga las tools y llama a la que necesita.
3. Devuelve el `structuredContent` de la tool; si la tool responde `isError`,
   lanza `McpCallError` con el código del servidor (`NOT_FOUND`, …); si el
   servidor no responde, rechaza el token o tarda más de 4 s, `McpUnavailable`.

Variables (`.env`): `MCP_SERVER_URL`, `MCP_AUTH_ISSUER`, `MCP_RESOURCE_URL`,
`MCP_AGENT_CLIENT_ID`, `MCP_AGENT_CLIENT_SECRET`. Ningún secreto en el código.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVER_NAME = "trackflow"
MCP_CALL_TIMEOUT_SECONDS = 4.0  # sesión MCP + llamada a la tool
TOKEN_TIMEOUT_SECONDS = 5.0
AGENT_SCOPES = ("incidents:read", "inventory:read")
# El agente solo usa tools de lectura; cualquier otra se rechaza aquí antes de salir.
AGENT_ALLOWED_TOOLS = frozenset({"incidents_get", "incidents_list", "inventory_list_products"})


class McpUnavailable(Exception):
    """El servidor MCP o el proveedor OAuth no respondieron, o rechazaron la conexión."""


class McpCallError(Exception):
    """La tool MCP respondió con `isError: true` y un código de error del servidor."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


def _env(name: str, default: str = "") -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")  # no sobrescribe variables ya definidas
    except ImportError:  # pragma: no cover
        pass
    return (os.environ.get(name) or default).strip()


def server_url() -> str:
    return _env("MCP_SERVER_URL", "http://localhost:8001/mcp")


# --------------------------------------------------------------------------- #
# Token OAuth (client_credentials)
# --------------------------------------------------------------------------- #
_token_lock = threading.Lock()
_token_cache: dict[str, Any] = {}
# Los tests sustituyen el transporte de httpx para el proveedor OAuth.
OAUTH_TRANSPORT = None


def _token_endpoint(client, issuer: str) -> str:
    discovery = client.get(f"{issuer}/.well-known/openid-configuration")
    discovery.raise_for_status()
    return discovery.json()["token_endpoint"]


def get_agent_token() -> str:
    """Access token del agente (cacheado). Lanza `McpUnavailable` si no se puede obtener."""
    with _token_lock:
        if _token_cache.get("token") and _token_cache.get("expires_at", 0) > time.time():
            return _token_cache["token"]
        issuer = _env("MCP_AUTH_ISSUER").rstrip("/")
        client_id, secret = _env("MCP_AGENT_CLIENT_ID"), _env("MCP_AGENT_CLIENT_SECRET")
        resource = _env("MCP_RESOURCE_URL")
        if not (issuer and client_id and secret and resource):
            raise McpUnavailable("Faltan MCP_AUTH_ISSUER, MCP_RESOURCE_URL o las credenciales del agente en .env")
        import httpx

        try:
            with httpx.Client(timeout=TOKEN_TIMEOUT_SECONDS, transport=OAUTH_TRANSPORT) as client:
                response = client.post(
                    _token_endpoint(client, issuer),
                    data={"grant_type": "client_credentials", "resource": resource, "scope": " ".join(AGENT_SCOPES)},
                    auth=(client_id, secret),
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise McpUnavailable(f"No se pudo obtener el token OAuth del agente ({type(exc).__name__})") from exc
        _token_cache["token"] = payload["access_token"]
        _token_cache["expires_at"] = time.time() + max(int(payload.get("expires_in", 3600)) - 60, 30)
        return _token_cache["token"]


def clear_token_cache() -> None:
    with _token_lock:
        _token_cache.clear()


# --------------------------------------------------------------------------- #
# Llamada a una tool MCP con langchain-mcp-adapters
# --------------------------------------------------------------------------- #
def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in content)
    return str(content or "")


def parse_tool_message(message: Any) -> dict[str, Any]:
    """`ToolMessage` del adaptador → datos estructurados, o `McpCallError` si la tool falló."""
    text = _text(getattr(message, "content", ""))
    if getattr(message, "status", "success") == "error":
        start = text.find("{")
        try:
            error = json.loads(text[start:])["error"]
            raise McpCallError(error["code"], error.get("message", ""), error.get("status"))
        except (ValueError, KeyError, TypeError):
            raise McpCallError("UNKNOWN", text[:300]) from None
    artifact = getattr(message, "artifact", None) or {}
    structured = artifact.get("structured_content") if isinstance(artifact, dict) else None
    if structured is not None:
        return structured
    try:
        return json.loads(text)
    except ValueError as exc:
        raise McpCallError("INVALID_RESPONSE", "La tool no devolvió datos estructurados") from exc


async def _acall(tool_name: str, arguments: dict[str, Any], token: str) -> dict[str, Any]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            SERVER_NAME: {
                "transport": "streamable_http",
                "url": server_url(),
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    )
    tools = await client.get_tools(server_name=SERVER_NAME)
    tool = next((candidate for candidate in tools if candidate.name == tool_name), None)
    if tool is None:
        raise McpUnavailable(f"El servidor MCP no publica la tool {tool_name}")
    message = await tool.ainvoke({"type": "tool_call", "id": f"agent-{tool_name}", "name": tool_name, "args": arguments})
    return parse_tool_message(message)


def _run(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:  # ya hay un bucle en este hilo
        return executor.submit(asyncio.run, coro).result()


def call_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoca una tool de lectura del servidor MCP y devuelve su salida estructurada."""
    if tool_name not in AGENT_ALLOWED_TOOLS:
        raise McpCallError("NOT_ALLOWED", f"El agente no usa la tool {tool_name} (solo lectura)")
    token = get_agent_token()
    try:
        return _run(asyncio.wait_for(_acall(tool_name, arguments, token), MCP_CALL_TIMEOUT_SECONDS))
    except (McpCallError, McpUnavailable):
        raise
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise McpUnavailable(f"timeout: el servidor MCP no respondió en {MCP_CALL_TIMEOUT_SECONDS:g} s") from exc
    except Exception as exc:  # conexión rechazada, 401/403 del middleware OAuth, ExceptionGroup de anyio…
        clear_token_cache()  # si el token caducó o fue revocado, la próxima llamada pide uno nuevo
        raise McpUnavailable(f"servidor MCP no disponible ({type(exc).__name__})") from exc
