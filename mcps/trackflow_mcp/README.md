# `trackflow_mcp` — servidor MCP de TrackFlow con OAuth (MCP Auth)

Expone el **Incidents Manager** (consultar, crear y cambiar el estado de incidencias) y el **inventario** (solo consulta) de TrackFlow a cualquier cliente MCP autorizado: el agente LangGraph del monorepo, MCP Playground u otros equipos. Se apoya en la API que ya existe (`services/api`) y no la reemplaza.

- SDK: `mcp` 1.30 (`FastMCP`) · Auth: `mcpauth` 0.2.0b1 (modo resource server) · Cliente del agente: `langchain-mcp-adapters` 0.3.2
- Proveedor OAuth 2.1 / OIDC: **Logto Cloud** (apps máquina-a-máquina, `client_credentials`)

## 1. Transporte: Streamable HTTP

| | stdio | **Streamable HTTP (elegido)** |
|---|---|---|
| Clientes | Un proceso local que lanza el servidor | Varios clientes remotos a la vez (Playground, agente, otros equipos) |
| Autenticación | No hay petición HTTP: no hay `Authorization` que validar | Bearer token en cada petición; Protected Resource Metadata (RFC 9728) |
| Despliegue | Junto al cliente | Servicio independiente (puerto 8001, reenviado por Codespaces) |

El enunciado pide un servicio **independiente, reutilizable y protegido con OAuth**: eso solo es posible con Streamable HTTP. El servidor corre en modo `stateless_http`: cada petición trae su token, se valida y se ejecuta sin depender de una sesión anterior.

## 2. Tools (discovery)

| Tool | Scope | Qué hace | API de TrackFlow |
|---|---|---|---|
| `incidents_list` | `incidents:read` | Busca incidencias (filtros `status`, `category`, `origin`, `branch`, `limit`) | `GET /api/incidents` |
| `incidents_get` | `incidents:read` | Una incidencia y sus `allowed_next_statuses` | `GET /api/incidents/{id}` |
| `incidents_create` | `incidents:write` | Crea una incidencia (nace `open`) | `POST /api/incidents` |
| `incidents_update_status` | `incidents:write` | Cambia el estado según el ciclo de vida | **`PATCH /api/incidents/{id}/status`** |
| `inventory_list_products` | `inventory:read` | Productos y stock (filtro por SKU exacto o por nombre) | `GET /inventory/products` |
| `inventory_get_product` | `inventory:read` | Un producto y su stock | `GET /inventory/products/{id}` |
| `inventory_update_stock` | — | **Siempre rechazada** con `READ_ONLY_RESOURCE` | ninguna |

Cada tool publica en el discovery (`tools/list`):
- `title` y `description` con el scope que exige y los errores relevantes;
- `inputSchema` con tipos, rangos y **los enums del Incidents Manager** (`open/in_progress/resolved/discarded`, `RETURN_REQUEST/DAMAGE/…`, `customer/branch/internal`, `Los Angeles/Zaragoza/central`);
- `outputSchema` (salida estructurada) y `annotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`).

Además, las `instructions` del servidor resumen qué se puede y qué no se puede hacer, los scopes y los códigos de error. Un agente externo lo entiende sin leer el código.

**Ciclo de vida:** `open → in_progress | discarded` · `in_progress → resolved | discarded` · `resolved` y `discarded` son finales. Una transición no válida la rechaza el propio Incidents Manager, y el servidor la devuelve como `INVALID_TRANSITION`.

## 3. Seguridad

### OAuth con MCP Auth
- `GET /.well-known/oauth-protected-resource/mcp` (público) publica la **Protected Resource Metadata**: recurso, proveedor (issuer de Logto) y `scopes_supported`.
- `/mcp` pasa por el `bearer_auth_middleware` de MCP Auth, que valida la firma JWT con el JWKS del proveedor, el issuer, la **audiencia** (`aud = MCP_RESOURCE_URL`) y la caducidad. Sin un token válido no se puede ni **listar** ni **invocar** ninguna tool.
- ⚠️ `mcpauth` 0.2.0b1 solo comprueba la audiencia si se le pasa `audience`; aquí se pasa siempre. Sin eso, un token emitido para otra API del mismo tenant serviría aquí.
- No se usa la auth integrada de FastMCP.

### Mínimo privilegio
- Tres scopes: `incidents:read`, `incidents:write` e `inventory:read`. **No existe `inventory:write`.**
- Cada tool declara su política en `service.TOOL_POLICIES` y la comprueba con los scopes del token (`INSUFFICIENT_SCOPE` si falta).
- La app del agente (`trackflow-agent`) solo tiene `incidents:read` + `inventory:read`. La app admin (`trackflow-mcp-admin`, para Playground) tiene los tres.

### Inventario de solo lectura, por diseño y en tres capas
1. No hay scope de escritura que se pueda conceder.
2. `inventory_update_stock` existe en el discovery solo para que cualquier intento se **rechace explícitamente** con `READ_ONLY_RESOURCE` (403), con cualquier token.
3. El cliente del backend (`backend.py`) solo permite una lista blanca de operaciones, y cualquier método distinto de `GET` sobre `/inventory` se corta antes de salir a la red.

### Códigos de error (distintos entre sí)

| Nivel | Código | HTTP / `status` | Cuándo |
|---|---|---|---|
| Transporte | `missing_auth_header` | 401 | Sin `Authorization` |
| Transporte | `invalid_auth_header_format` | 401 | La cabecera no es `Bearer …` |
| Transporte | `invalid_token` | 401 | Firma no válida, caducado o mal formado |
| Transporte | `invalid_issuer` / `invalid_audience` | 401 | Token de otro proveedor o de otro recurso |
| Tool | `INSUFFICIENT_SCOPE` | 403 | Falta el scope de la tool |
| Tool | `READ_ONLY_RESOURCE` | 403 | Intento de escribir en el inventario |
| Tool | `VALIDATION_ERROR` | 422 | Argumentos fuera del esquema (con la lista de campos) |
| Tool | `NOT_FOUND` | 404 | Incidencia o producto inexistente |
| Tool | `INVALID_TRANSITION` | 409 | El ciclo de vida no permite ese cambio |
| Tool | `UPSTREAM_UNAVAILABLE` | 503 | La API de TrackFlow no responde (timeout de 5 s) |
| Tool | `UNKNOWN_TOOL` | 404 | Tool inexistente |
| Tool | `INTERNAL_ERROR` | 500 | Error no previsto (sin detalles internos) |

Los errores de transporte llevan `WWW-Authenticate: Bearer error="…", resource_metadata="…/.well-known/oauth-protected-resource/mcp"`. Los de tool son un `CallToolResult` con `isError: true` y el texto `{"error": {"code", "status", "message", …}}`.

### Log de auditoría
Cada invocación (incluidas las rechazadas por scope, validación o solo lectura) escribe una línea JSON en `logs/mcp-tool-calls.jsonl` (ignorado por git) y en la consola del servidor:

```json
{"ts": "...", "tool": "incidents_update_status", "client_id": "<app id>", "subject": "<app id>", "scopes": ["incidents:read", "incidents:write", "inventory:read"], "result": "ok", "status": 200, "duration_ms": 41.2, "argument_names": ["incident_id", "status"]}
```

Se registran los **nombres** de los argumentos, nunca sus valores.

## 4. Configuración (`.env`)

```dotenv
MCP_AUTH_ISSUER=https://<tenant>.logto.app/oidc
MCP_RESOURCE_URL=https://<codespace>-8001.app.github.dev/mcp   # = API identifier en Logto = aud del token
MCP_SERVER_URL=http://localhost:8001/mcp                       # cómo llega el agente al servidor
TRACKFLOW_API_URL=http://localhost:8000
MCP_ADMIN_CLIENT_ID=...      MCP_ADMIN_CLIENT_SECRET=...       # app trackflow-mcp-admin (Playground)
MCP_AGENT_CLIENT_ID=...      MCP_AGENT_CLIENT_SECRET=...       # app trackflow-agent (solo lectura)
```

En Logto: un **API resource** con identifier = `MCP_RESOURCE_URL` y los permisos `incidents:read`, `incidents:write` e `inventory:read`; los roles M2M `mcp-full-access` y `agent-readonly`, y las apps M2M `trackflow-mcp-admin` y `trackflow-agent`.

## 5. Ejecutar y probar

```bash
uvicorn services.api.main:app --port 8000          # API de TrackFlow
python -m mcps.trackflow_mcp                         # servidor MCP en :8001
python scripts/mcp_get_token.py                      # token (app admin) para MCP Playground
python scripts/mcp_smoke_test.py                     # flujo completo → docs/mcp/smoke-test.txt
python -m pytest tests/mcps                          # pruebas del servidor
```

**MCP Playground:** en Codespaces, pestaña **Puertos** → puerto 8001 → *Port visibility: Public*. En `https://www.mcpplayground.tech/playground`, conecta con la URL `https://<codespace>-8001.app.github.dev/mcp` (no `localhost`) y pega el token en el campo Bearer.

## 6. Cliente: el agente LangGraph

`services/agent/mcp_client.py` obtiene el token del agente (`client_credentials`, solo lectura, cacheado), carga las tools con `MultiServerMCPClient` (`streamable_http`) y las invoca. Los nodos `lookup_ticket` y `lookup_inventory` del grafo usan ese cliente. La llamada HTTP directa de la Parte 2 se eliminó: el agente tiene un único camino hacia el Incidents Manager.
