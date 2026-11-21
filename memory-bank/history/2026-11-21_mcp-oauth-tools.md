# Plan y registro — Servidor MCP: conectando el agente con las herramientas de la empresa (TrackFlow)

> **Proyecto 4Geeks:** "Servidor MCP: Conectando tu Agente con las Herramientas de la Empresa".
> **Rama:** `feature/mcp-oauth-tools`, creada por Marisin **desde `feature/langgraph-external-tools`** (PR #30, pendiente). El proyecto migra el nodo `lookup_ticket`, que solo existe en esa rama.
> **Dependencias** (Marisin, `uv add`, commit `chore: añade mcp, mcpauth y langchain-mcp-adapters`): `mcp` 1.30.0, `mcpauth` **0.2.0b1** (fijada a mano: la 0.1.1 estable no tiene Protected Resource Metadata) y `langchain-mcp-adapters` 0.3.2.
> **Decisiones de Marisin:** proveedor OAuth **Logto Cloud**; migrar al MCP **las dos tools** del agente (incidentes e inventario).

## 0. Reglas
1. Un commit por acción, con prefijo convencional y descripción en español. El parche no toca `pyproject.toml` ni `uv.lock`.
2. El servidor vive en `mcps/` y se apoya en la API existente, sin reimplementarla.
3. Los cambios de estado van siempre por `PATCH /api/incidents/{id}/status`.
4. OAuth solo con MCP Auth; nunca con la auth integrada de FastMCP. Ningún secreto en el código ni en el repo.
5. El agente debe tener un único camino hacia el Incidents Manager: el servidor MCP.

## 1. Rúbrica → dónde se cumple

| Criterio | Dónde |
|---|---|
| Servidor bajo `mcps/`, arranca y expone tools por discovery | `mcps/trackflow_mcp/` · `python -m mcps.trackflow_mcp` · `tools/list` |
| Sin token válido no se lista ni se ejecuta nada | `bearer_auth_middleware` de MCP Auth sobre `/mcp` (con `audience`) · tests de 401 |
| Tickets: crear, `PATCH …/status` y consultar contra el gestor real | `incidents_create`, `incidents_update_status`, `incidents_get`/`incidents_list` → `backend.py` |
| Inventario: consulta y rechazo explícito de escritura | `inventory_list_products`, `inventory_get_product` · `inventory_update_stock` → `READ_ONLY_RESOURCE` · lista blanca en `backend.py` |
| Descripción y esquema claros en el discovery | `title`, `description` (con scope), `inputSchema` con enums, `outputSchema`, `annotations`, `instructions` |
| Errores de auth, autorización y validación distintos | 401 `missing_auth_header`/`invalid_token`/`invalid_audience`… · `INSUFFICIENT_SCOPE` · `VALIDATION_ERROR` … (`errors.py`) |
| Log por invocación (cliente, tool, resultado) | `audit.py` → `logs/mcp-tool-calls.jsonl` + consola |
| El agente ya no llama al Incidents Manager directamente | `services/agent/mcp_client.py`; `http_get_json` eliminado; test AST + eval E13 |
| MCP Playground con la URL pública de Codespaces | Puerto 8001 público + token de `scripts/mcp_get_token.py` (evidencia de Marisin) |

## 2. Decisiones (M1–M12)

| # | Decisión | Por qué |
|---|---|---|
| M1 | **Streamable HTTP**, `stateless_http=True`, puerto 8001, endpoint `/mcp`. | Varios clientes remotos; la auth MCP se define sobre HTTP; cada petición trae su token. |
| M2 | `FastMCP` del SDK oficial `mcp` 1.30. | Es el que usa MCP Auth en sus ejemplos; da `outputSchema` y `annotations`. |
| M3 | MCP Auth en modo resource server: `fetch_server_config(issuer, OIDC)`, `ResourceServerMetadata(resource, authorization_servers, scopes_supported)`, `resource_metadata_router()` y `bearer_auth_middleware("jwt", resource=…, audience=…)`. | Protected Resource Metadata (RFC 9728) y validación JWT. **`audience` explícito**: la 0.2.0b1 no comprueba `aud` si no se le pasa. |
| M4 | Proveedor: Logto Cloud, `client_credentials` (apps M2M), API resource = `MCP_RESOURCE_URL`. | Verificado por MCP Auth; sin infraestructura en el Codespace (disco al 90 %). |
| M5 | Scopes `incidents:read`, `incidents:write`, `inventory:read`; sin `inventory:write`. Política por tool en `TOOL_POLICIES`. | Mínimo privilegio. |
| M6 | `inventory_update_stock` siempre rechaza (`READ_ONLY_RESOURCE`) + lista blanca de operaciones en `backend.py`. | "Rechazar explícitamente, no simplemente omitir". |
| M7 | Errores con código estable en `CallToolResult.isError` (JSON) y 401 en el transporte. `TrackFlowMCP.call_tool` traduce cualquier fallo (incluida la validación de argumentos del SDK) a su código. | Códigos distintos para auth, autorización y validación. |
| M8 | Log JSONL por invocación (también las rechazadas), con los nombres de los argumentos pero no sus valores. | Trazabilidad sin volcar datos. |
| M9 | Protección anti DNS-rebinding del SDK desactivada y CORS abierto (`MCP_ALLOWED_ORIGINS`). | Los clientes llegan por la URL pública de Codespaces y desde el navegador (Playground); el control de acceso lo hace OAuth. |
| M10 | Agente: `mcp_client.py` con `MultiServerMCPClient` (`streamable_http`), token `client_credentials` **solo lectura** cacheado, timeout 4 s, lista blanca de tools de lectura. | Migración pedida; mínimo privilegio también en el cliente. |
| M11 | `tools.py` conserva los contratos (`TicketQuery`, `ToolResult`…) y cambia solo el transporte; `ToolResult` añade `transport="mcp"` y `mcp_tool`. | El enrutamiento RAG/tools y la composición no cambian. |
| M12 | Evals: el caso de "servicio caído" apunta el cliente MCP a un puerto cerrado (`mcp_url`); nuevo E13 (todas las consultas pasan por MCP). | Confirmar que el enrutamiento sigue igual con el cliente MCP. |

## 3. Commits

| # | Acción | Commit |
|---|---|---|
| 0 | **Marisin:** `uv add` | `chore: añade mcp, mcpauth y langchain-mcp-adapters` |
| 1 | Este plan | `docs: añade el plan del servidor MCP con OAuth` |
| 2 | Config, errores, modelos, backend, auditoría y servicio | `feat: añade la lógica de las tools del servidor MCP con permisos por scope` |
| 3 | `server.py`, `__main__.py` | `feat: expone el servidor MCP por Streamable HTTP protegido con MCP Auth` |
| 4 | `mcps/trackflow_mcp/README.md` | `docs: documenta el servidor MCP, sus tools, scopes y errores` |
| 5 | `services/agent/mcp_client.py`, `tools.py` | `feat: migra las tools del agente al servidor MCP como cliente` |
| 6 | Tests del servidor | `test: añade pruebas del servidor MCP, su OAuth y su discovery` |
| 7 | Tests del agente | `test: adapta las pruebas del agente al cliente MCP` |
| 8 | Evals + grabador | `test: verifica en los evals que las tools pasan por el servidor MCP` |
| 9 | Scripts de token y smoke test | `feat: añade scripts para obtener el token y probar el servidor MCP` |
| 10 | `.env.example`, CI | `chore: documenta la configuración del servidor MCP y lo añade al CI` |
| 11 | `progress.md`, diseño del agente | `docs: registra el servidor MCP en progress` |
| 12 | **Marisin:** traces, smoke test, Playground | evidencias |

## 4. Verificación (Marisin)
1. Configurar Logto y `.env`.
2. `python -m pytest -q --ignore=tests/pipelines/test_agent_evals.py`.
3. API + servidor MCP en marcha → `python scripts/mcp_smoke_test.py`.
4. Puerto 8001 público → MCP Playground con la URL reenviada y el token: un flujo por tool, el intento de escritura en inventario y el acceso sin token.
5. Qdrant + API + MCP → `python scripts/agent_record_traces.py` y evals.

## 5. Registro
- 2026-11-21 — Plan y parche preparados por Claude. La API de `mcp` 1.30.0, `mcpauth` 0.2.0b1 y `langchain-mcp-adapters` 0.3.2 se verificó leyendo su código fuente (no se pueden instalar en el entorno de Claude). La lógica de las tools, los permisos y el cliente del agente se probaron en local con dobles; los tests con `mcp`/`mcpauth`/`httpx` se ejecutan en el Codespace.
