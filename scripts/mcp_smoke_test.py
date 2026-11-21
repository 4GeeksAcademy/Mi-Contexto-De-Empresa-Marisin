"""Prueba de humo del servidor MCP de TrackFlow como cliente externo (evidencia para el PR).

Recorre, contra el servidor en marcha, un flujo completo por cada tool y los
casos de seguridad, y deja la salida en `docs/mcp/smoke-test.txt`:

1. Sin token → HTTP 401 (`missing_auth_header`); con un token inventado → 401 (`invalid_token`).
2. Discovery con token: lista de tools con su título y scope.
3. Incidencias (token admin): crear → consultar → pasar a `in_progress` → listar;
   transición no válida → `INVALID_TRANSITION`.
4. Inventario: listar productos y consultar uno por id.
5. Intento de escritura en inventario → `READ_ONLY_RESOURCE`.
6. Token del agente (solo lectura) intentando crear una incidencia → `INSUFFICIENT_SCOPE`.
7. Argumentos inválidos → `VALIDATION_ERROR`.

Necesita la API (8000), el servidor MCP (8001) y el `.env` con las credenciales de Logto.

    python scripts/mcp_smoke_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mcp_get_token import request_token  # noqa: E402

OUTPUT = ROOT / "docs" / "mcp" / "smoke-test.txt"
LINES: list[str] = []


def log(text: str = "") -> None:
    print(text)
    LINES.append(text)


def server_url() -> str:
    return os.environ.get("MCP_SERVER_URL") or "http://localhost:8001/mcp"


def raw_unauthenticated_checks() -> None:
    import httpx

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    for label, extra in (("sin token", {}), ("token inventado", {"Authorization": "Bearer no-es-un-jwt"})):
        response = httpx.post(server_url(), json=body, headers={**headers, **extra}, timeout=10)
        log(f"[{label}] HTTP {response.status_code} · WWW-Authenticate: {response.headers.get('www-authenticate', '—')}")


async def run_flows(admin_token: str, agent_token: str) -> None:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    def client_for(token: str):
        return MultiServerMCPClient(
            {"trackflow": {"transport": "streamable_http", "url": server_url(), "headers": {"Authorization": f"Bearer {token}"}}}
        )

    admin_tools = {tool.name: tool for tool in await client_for(admin_token).get_tools(server_name="trackflow")}
    agent_tools = {tool.name: tool for tool in await client_for(agent_token).get_tools(server_name="trackflow")}
    log("\n## Discovery (tools publicadas)")
    for name, tool in admin_tools.items():
        log(f"- {name}: {tool.description[:110]}…")

    async def call(tools, name, args, label):
        message = await tools[name].ainvoke({"type": "tool_call", "id": name, "name": name, "args": args})
        artifact = getattr(message, "artifact", None) or {}
        data = artifact.get("structured_content") if isinstance(artifact, dict) else None
        text = data if data is not None else "".join(b.get("text", "") for b in message.content if isinstance(b, dict))
        status = "ERROR" if message.status == "error" else "OK"
        log(f"\n### {label} → {name} [{status}]\n{json.dumps(text, ensure_ascii=False, indent=2) if not isinstance(text, str) else text}")
        return data

    log("\n## Incidencias (token admin)")
    created = await call(admin_tools, "incidents_create", {
        "title": "Prueba MCP: etiqueta ilegible", "description": "Creada desde el smoke test del servidor MCP.",
        "category": "WRONG_ADDRESS", "origin": "internal", "branch": "Los Angeles"}, "Crear")
    incident_id = int(created["id"])
    await call(admin_tools, "incidents_get", {"incident_id": incident_id}, "Consultar")
    await call(admin_tools, "incidents_update_status", {"incident_id": incident_id, "status": "in_progress"}, "Actualizar estado")
    await call(admin_tools, "incidents_update_status", {"incident_id": incident_id, "status": "open"}, "Transición no válida")
    await call(admin_tools, "incidents_list", {"status": "in_progress", "limit": 3}, "Listar en curso")

    log("\n## Inventario (solo lectura)")
    products = await call(admin_tools, "inventory_list_products", {"name_contains": "", "limit": 2}, "Listar productos")
    if products and products.get("items"):
        await call(admin_tools, "inventory_get_product", {"product_id": products["items"][0]["id"]}, "Consultar producto")
    await call(admin_tools, "inventory_update_stock", {"product_id": 1, "new_stock": 0}, "Intento de escritura")

    log("\n## Mínimo privilegio y validación")
    await call(agent_tools, "incidents_create", {
        "title": "x", "description": "y", "category": "DAMAGE", "origin": "customer", "branch": "Zaragoza"}, "Agente (solo lectura) intenta crear")
    await call(admin_tools, "incidents_list", {"status": "cerrado"}, "Argumento inválido")


def main() -> int:
    log("# Prueba de humo · servidor MCP de TrackFlow")
    log(f"Servidor: {server_url()}\n\n## Autenticación")
    raw_unauthenticated_checks()
    admin = request_token("admin")["access_token"]
    agent = request_token("agent")["access_token"]
    asyncio.run(run_flows(admin, agent))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(LINES) + "\n", encoding="utf-8")
    print(f"\nSalida guardada en {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
