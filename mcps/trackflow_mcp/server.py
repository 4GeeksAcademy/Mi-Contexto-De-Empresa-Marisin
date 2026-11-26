"""Servidor MCP de TrackFlow (Streamable HTTP) protegido con OAuth vía MCP Auth.

Arquitectura:

* **Transporte: Streamable HTTP** en `/mcp`. El servidor lo consumen varios
  clientes remotos (MCP Playground, el agente LangGraph, otros equipos), y la
  autorización de MCP se define sobre HTTP: con `stdio` no habría cabecera
  `Authorization` que validar. `stateless_http=True`: cada petición se valida y
  ejecuta de forma independiente (la identidad del token viaja con la petición).
* **MCP Auth (`mcpauth`) en modo resource server**: sirve la Protected Resource
  Metadata (RFC 9728) en `/.well-known/oauth-protected-resource/mcp` y su
  middleware valida el JWT bearer (firma con JWKS, issuer, **audiencia** =
  `MCP_RESOURCE_URL`, caducidad) antes de que ningún cliente pueda listar o
  invocar tools. No se usa la auth integrada de FastMCP.
* **Permisos por tool** (`service.TOOL_POLICIES`): cada tool exige su scope;
  la escritura de inventario se rechaza explícitamente.
* **Errores y log centralizados** en `TrackFlowMCP.call_tool`: todo resultado de
  error lleva un código estable (`errors.py`) y cada invocación queda en el log
  de auditoría (`audit.py`).
"""

from __future__ import annotations

import contextlib
import time
from typing import Annotated, Any, Callable, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BeforeValidator, Field, ValidationError
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Mount

from packages.shared.incident_validation import (
    IncidentBranch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
)

from .audit import AuditLog
from .backend import BackendClient
from .config import SCOPES_SUPPORTED, Settings, load_settings
from .errors import McpToolError
from .models import Incident, IncidentList, Product, ProductList
from .service import Caller, TrackFlowTools

SERVER_NAME = "TrackFlow MCP"
INSTRUCTIONS = """Servidor MCP de TrackFlow (logística de última milla, almacenes de Los Ángeles y Zaragoza).

Qué puedes hacer:
- Incidencias (Incidents Manager): consultar (incidents_list, incidents_get), crear (incidents_create) y cambiar
  su estado siguiendo el ciclo de vida open → in_progress → resolved, o → discarded (incidents_update_status).
- Inventario: SOLO consultar productos y stock (inventory_list_products, inventory_get_product).
  inventory_update_stock existe únicamente para dejar explícito que el inventario no se puede modificar: siempre
  devuelve el error READ_ONLY_RESOURCE.

Autenticación: OAuth 2.1 (bearer JWT). Scopes: incidents:read, incidents:write, inventory:read.
Cada tool indica en su descripción el scope que exige.

Errores: los resultados con isError=true llevan un JSON {"error": {"code", "status", "message"}} con estos
códigos: INSUFFICIENT_SCOPE (403), READ_ONLY_RESOURCE (403), VALIDATION_ERROR (422), NOT_FOUND (404),
INVALID_TRANSITION (409), UPSTREAM_UNAVAILABLE (503), UNKNOWN_TOOL (404), INTERNAL_ERROR (500).
Sin token o con un token inválido, el servidor responde HTTP 401 antes de ejecutar nada."""

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
REJECTED = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)

IncidentId = Annotated[int, Field(ge=1, description="Id de la incidencia en el Incidents Manager (p. ej. 3).")]


def _blank_to_none(value: Any) -> Any:
    """Los clientes de formulario (MCP Playground) envían "" en los filtros que se dejan vacíos."""
    return None if isinstance(value, str) and not value.strip() else value


Blank = BeforeValidator(_blank_to_none)
Limit = Annotated[int, Field(ge=1, le=100, description="Número máximo de resultados (1-100).")]


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors(include_url=False)
    ]


def to_mcp_error(tool: str, exc: ToolError) -> McpToolError:
    """Traduce cualquier fallo de una tool a un error con código estable (sin detalles internos)."""
    cause = exc.__cause__
    if isinstance(cause, McpToolError):
        return cause
    if isinstance(cause, ValidationError):
        return McpToolError(
            "VALIDATION_ERROR", f"Argumentos no válidos para {tool}.", errors=_validation_details(cause)
        )
    if str(exc).startswith("Unknown tool"):
        return McpToolError("UNKNOWN_TOOL", f"La tool '{tool}' no existe en este servidor.")
    return McpToolError("INTERNAL_ERROR", f"Error interno al ejecutar {tool}.")


class TrackFlowMCP(FastMCP):
    """FastMCP con errores codificados y log de auditoría en cada invocación de tool."""

    def __init__(self, *args, audit: AuditLog, caller: Callable[[], Caller], **kwargs):
        super().__init__(*args, **kwargs)
        self.audit = audit
        self.current_caller = caller

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        caller = self.current_caller()
        started = time.perf_counter()
        try:
            result = await super().call_tool(name, arguments)
        except ToolError as exc:
            error = to_mcp_error(name, exc)
            self._audit(name, caller, error.code, error.status, started, arguments)
            raise ToolError(error.to_json()) from exc
        self._audit(name, caller, "ok", 200, started, arguments)
        return result

    def _audit(self, tool, caller, result, status, started, arguments):
        self.audit.record(
            tool=tool,
            client_id=caller.client_id,
            subject=caller.subject,
            scopes=caller.scopes,
            result=result,
            status=status,
            duration_ms=(time.perf_counter() - started) * 1000,
            arguments=arguments,
        )


def build_mcp(tools: TrackFlowTools, audit: AuditLog, caller: Callable[[], Caller]) -> TrackFlowMCP:
    """Crea el servidor MCP y registra las tools con descripciones y esquemas completos."""
    mcp = TrackFlowMCP(
        SERVER_NAME,
        instructions=INSTRUCTIONS,
        stateless_http=True,
        # Los clientes llegan por la URL pública de Codespaces y desde navegadores: la protección
        # anti DNS-rebinding (pensada para servidores sin auth en localhost) se sustituye por OAuth.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        audit=audit,
        caller=caller,
    )

    @mcp.tool(
        title="Buscar incidencias",
        annotations=READ,
        description=(
            "Lista incidencias del Incidents Manager de TrackFlow, de la actualizada más recientemente a la más "
            "antigua, con filtros opcionales. Solo lectura. Requiere el scope incidents:read."
        ),
    )
    def incidents_list(
        status: Annotated[Optional[IncidentStatus], Blank, Field(description="Filtra por estado (vacío = todos).")] = None,
        category: Annotated[Optional[IncidentCategory], Blank, Field(description="Filtra por categoría (vacío = todas).")] = None,
        origin: Annotated[Optional[IncidentOrigin], Blank, Field(description="Filtra por origen (vacío = todos).")] = None,
        branch: Annotated[Optional[IncidentBranch], Blank, Field(description="Filtra por sucursal (vacío = todas).")] = None,
        limit: Limit = 20,
    ) -> IncidentList:
        return tools.incidents_list(caller(), status=status, category=category, origin=origin, branch=branch, limit=limit)

    @mcp.tool(
        title="Consultar una incidencia",
        annotations=READ,
        description=(
            "Devuelve una incidencia por su id, con su estado actual y los estados a los que puede pasar "
            "(allowed_next_statuses). Error NOT_FOUND si no existe. Requiere el scope incidents:read."
        ),
    )
    def incidents_get(incident_id: IncidentId) -> Incident:
        return tools.incidents_get(caller(), incident_id=incident_id)

    @mcp.tool(
        title="Crear una incidencia",
        annotations=WRITE,
        description=(
            "Crea una incidencia en el Incidents Manager (POST /api/incidents). Siempre nace en estado 'open'. "
            "Requiere el scope incidents:write."
        ),
    )
    def incidents_create(
        title: Annotated[str, Field(min_length=1, max_length=200, description="Resumen corto de la incidencia.")],
        description: Annotated[str, Field(min_length=1, max_length=2000, description="Qué ha pasado, con detalle.")],
        category: Annotated[IncidentCategory, Field(description="Tipo de incidencia.")],
        origin: Annotated[IncidentOrigin, Field(description="Quién la reporta: customer, branch o internal.")],
        branch: Annotated[IncidentBranch, Field(description="Sucursal afectada.")],
    ) -> Incident:
        return tools.incidents_create(
            caller(), title=title, description=description, category=category, origin=origin, branch=branch
        )

    @mcp.tool(
        title="Cambiar el estado de una incidencia",
        annotations=WRITE,
        description=(
            "Cambia el estado de una incidencia por el endpoint de ciclo de vida del Incidents Manager "
            "(PATCH /api/incidents/{id}/status). Transiciones válidas: open → in_progress | discarded; "
            "in_progress → resolved | discarded; resolved y discarded son finales. Una transición no válida da "
            "INVALID_TRANSITION. Requiere el scope incidents:write."
        ),
    )
    def incidents_update_status(
        incident_id: IncidentId,
        status: Annotated[IncidentStatus, Field(description="Nuevo estado.")],
    ) -> Incident:
        return tools.incidents_update_status(caller(), incident_id=incident_id, status=status)

    @mcp.tool(
        title="Consultar productos del inventario",
        annotations=READ,
        description=(
            "Consulta productos del inventario con su stock total entre almacenes. Filtra por código SKU exacto "
            "o por parte del nombre. Solo lectura. Requiere el scope inventory:read."
        ),
    )
    def inventory_list_products(
        sku: Annotated[Optional[str], Blank, Field(max_length=64, description="Código SKU exacto (sin distinguir mayúsculas).")] = None,
        name_contains: Annotated[Optional[str], Blank, Field(max_length=80, description="Texto contenido en el nombre del producto.")] = None,
        limit: Limit = 20,
    ) -> ProductList:
        return tools.inventory_list_products(caller(), sku=sku, name_contains=name_contains, limit=limit)

    @mcp.tool(
        title="Consultar un producto del inventario",
        annotations=READ,
        description="Devuelve un producto del inventario por su id, con su stock actual. Solo lectura. Requiere el scope inventory:read.",
    )
    def inventory_get_product(
        product_id: Annotated[int, Field(ge=1, description="Id del producto en el inventario.")],
    ) -> Product:
        return tools.inventory_get_product(caller(), product_id=product_id)

    @mcp.tool(
        title="Modificar stock (NO PERMITIDO)",
        annotations=REJECTED,
        description=(
            "NO PERMITIDO. El inventario es de solo lectura a través de este servidor: esta tool existe solo para "
            "que cualquier intento de modificar el stock se rechace de forma explícita. Siempre devuelve el error "
            "READ_ONLY_RESOURCE (403), sea cual sea el token. Para consultar el stock usa inventory_list_products."
        ),
    )
    def inventory_update_stock(
        product_id: Annotated[int, Field(ge=1, description="Id del producto.")],
        new_stock: Annotated[int, Field(ge=0, description="Stock que se intentaría fijar (se rechaza).")],
    ) -> dict:
        tools.inventory_update_stock(caller(), product_id=product_id, new_stock=new_stock)
        return {}  # nunca se alcanza: la política siempre lanza READ_ONLY_RESOURCE

    return mcp


def create_app(
    settings: Settings | None = None,
    *,
    auth_server_config=None,
    verify: Any = "jwt",
    backend: BackendClient | None = None,
) -> Starlette:
    """App ASGI: Protected Resource Metadata (pública) + `/mcp` protegido por MCP Auth.

    `auth_server_config` y `verify` permiten a los tests usar un proveedor y una
    verificación de token simulados; en producción se descubre el proveedor con
    `fetch_server_config(MCP_AUTH_ISSUER)` y se validan JWT reales.
    """
    from mcpauth import MCPAuth
    from mcpauth.config import AuthServerType
    from mcpauth.types import ResourceServerConfig, ResourceServerMetadata
    from mcpauth.utils import fetch_server_config

    settings = settings or load_settings()
    if auth_server_config is None:
        if not settings.auth_issuer:
            raise RuntimeError("Falta MCP_AUTH_ISSUER en .env: el servidor MCP no arranca sin proveedor OAuth.")
        auth_server_config = fetch_server_config(settings.auth_issuer, AuthServerType.OIDC)

    mcp_auth = MCPAuth(
        protected_resources=[
            ResourceServerConfig(
                metadata=ResourceServerMetadata(
                    resource=settings.resource_url,
                    authorization_servers=[auth_server_config],
                    scopes_supported=list(SCOPES_SUPPORTED),
                    resource_name=SERVER_NAME,
                )
            )
        ]
    )

    def current_caller() -> Caller:
        info = mcp_auth.auth_info
        if info is None:
            return Caller(client_id=None, subject=None, scopes=[])
        return Caller(client_id=info.client_id, subject=info.subject, scopes=list(info.scopes or []))

    audit = AuditLog(settings.audit_log)
    mcp = build_mcp(TrackFlowTools(backend or BackendClient(settings.api_url, service_key=settings.service_key)), audit, current_caller)

    # `audience` es imprescindible: MCP Auth 0.2.0b1 solo comprueba el `aud` del token si se le pasa.
    bearer_auth = Middleware(
        mcp_auth.bearer_auth_middleware(verify, resource=settings.resource_url, audience=settings.resource_url)
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        async with mcp.session_manager.run():
            yield

    app = Starlette(
        routes=[
            *mcp_auth.resource_metadata_router().routes,
            Mount("/", app=mcp.streamable_http_app(), middleware=[bearer_auth]),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=list(settings.allowed_origins),
                allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
                allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id", "Mcp-Protocol-Version", "Last-Event-ID"],
                expose_headers=["Mcp-Session-Id", "WWW-Authenticate"],
            )
        ],
        lifespan=lifespan,
    )
    app.state.mcp = mcp
    app.state.mcp_auth = mcp_auth
    return app
