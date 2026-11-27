"""Validación de cada llamada a una tool **antes de ejecutarla** (proyecto NIST · Protect / OWASP LLM05-LLM06).

El enrutador (LLM o reglas) decide qué tool usar y con qué argumentos: es salida
de un modelo, así que no se ejecuta sin revisarla. Hasta ahora había tres
controles sueltos (contrato `RouteDecision`, guardas de anclaje del enrutador y la
lista blanca de `mcp_client`); este módulo es la **única puerta** por la que pasa
toda llamada (`tools.call_mcp`) y decide con cuatro reglas, en este orden:

1. **Tool conocida.** Solo existen las tools de este catálogo. Cualquier otro
   nombre (alucinado, inyectado en un documento…) → `unknown_tool`.
2. **Acción irreversible o de escritura → confirmación humana explícita.** Las
   acciones del BRIEFING §5 y las tools de escritura del servidor MCP solo pasan
   con una `HumanConfirmation` válida (persona de staff, distinta del agente,
   para esa acción concreta). El agente de CX **nunca** la tiene: es de solo
   lectura, así que en la práctica siempre se rechazan (`human_confirmation_required`).
3. **Argumentos con su contrato.** Cada tool de lectura tiene un esquema
   estricto (`extra="forbid"`, tipos, rangos, longitudes). Un argumento de más o
   fuera de rango → `invalid_arguments`.
4. **Sin instrucciones en los argumentos.** Ningún texto de un argumento puede
   tener forma de orden o de marcador de rol (las mismas reglas que la guardia de
   entrada) → `instruction_in_arguments`.

Cada rechazo deja un evento de guardrail (`guard = tool_call`, tipo `security`)
en el log, en el registro y en el trace de la corrida.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from packages.shared.incident_validation import IncidentBranch, IncidentCategory, IncidentOrigin, IncidentStatus

from . import events
from .input_guard import ROLE_MARKERS, injection_rules

STAFF_ROLES = frozenset({"admin", "manager"})
MAX_LIMIT = 20

ToolKind = Literal["read", "write", "irreversible"]
RejectReason = Literal[
    "unknown_tool", "human_confirmation_required", "invalid_confirmation", "invalid_arguments",
    "instruction_in_arguments",
]


# --------------------------------------------------------------------------- #
# Contratos de los argumentos de las tools de lectura
# --------------------------------------------------------------------------- #
class IncidentsGetArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: int = Field(ge=1, le=10**9)


class IncidentsListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: IncidentStatus | None = None
    category: IncidentCategory | None = None
    origin: IncidentOrigin | None = None
    branch: IncidentBranch | None = None
    limit: int = Field(default=5, ge=1, le=MAX_LIMIT)


class InventoryListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[\w.\-/ ]+$")
    name_contains: str | None = Field(default=None, min_length=2, max_length=80)
    limit: int = Field(default=5, ge=1, le=MAX_LIMIT)

    @model_validator(mode="after")
    def _one_criterion(self) -> "InventoryListArgs":
        if not (self.sku or self.name_contains):
            raise ValueError("Indica un SKU o un nombre de producto")
        return self


READ_TOOLS: dict[str, type[BaseModel]] = {
    "incidents_get": IncidentsGetArgs,
    "incidents_list": IncidentsListArgs,
    "inventory_list_products": InventoryListArgs,
}

# Tools de escritura que publica el servidor MCP (mcps/trackflow_mcp): el agente no las usa.
WRITE_TOOLS = frozenset({"incidents_create", "incidents_update_status", "inventory_update_stock"})


# --------------------------------------------------------------------------- #
# Acciones irreversibles del BRIEFING §5
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class IrreversibleAction:
    action_id: str
    briefing: str
    description: str
    tools: tuple[str, ...]
    control: str


IRREVERSIBLE_ACTIONS: tuple[IrreversibleAction, ...] = (
    IrreversibleAction(
        "approve_return_above_threshold", "§5.1",
        "Aprobar una devolución por encima de un valor monetario definido por el equipo",
        ("returns_approve", "approve_return"),
        "El motor de devoluciones no existe en el fork; cualquier tool así exige confirmación humana.",
    ),
    IrreversibleAction(
        "confirm_high_value_dispatch", "§5.2",
        "Confirmar el despacho de un envío de alto valor sin validación adicional",
        ("dispatch_confirm", "confirm_dispatch", "inventory_create_outbound"),
        "POST /inventory/orders/outbound: solo staff y, por encima del umbral, confirm_high_value=true "
        "tras confirmar la persona en el backoffice (409 si falta).",
    ),
    IrreversibleAction(
        "change_carrier_in_transit", "§5.3",
        "Cambiar el carrier asignado a un envío ya en tránsito",
        ("shipment_change_carrier", "carrier_assign", "change_carrier"),
        "El motor de carriers no existe; el agente no tiene tools de escritura (caso 2 del BRIEFING probado).",
    ),
    IrreversibleAction(
        "share_b2b_data_cross_brand", "§5.4",
        "Compartir datos de volumen o incidentes de una marca cliente (B2B) con otra",
        ("b2b_share_report", "share_client_data", "reporting_export"),
        "ACL de tools por rol (OWASP C2) y require_staff en /rfp y /reporting (C4).",
    ),
)
IRREVERSIBLE_TOOLS: dict[str, IrreversibleAction] = {
    tool: action for action in IRREVERSIBLE_ACTIONS for tool in action.tools
}


def tool_kind(tool_name: str) -> ToolKind | None:
    if tool_name in READ_TOOLS:
        return "read"
    if tool_name in IRREVERSIBLE_TOOLS:
        return "irreversible"
    if tool_name in WRITE_TOOLS:
        return "write"
    return None


# --------------------------------------------------------------------------- #
# Confirmación humana y veredicto
# --------------------------------------------------------------------------- #
class HumanConfirmation(BaseModel):
    """Confirmación explícita de una persona de staff para **una** acción concreta."""

    model_config = ConfigDict(extra="forbid")

    action: str = Field(min_length=1, description="Nombre de la tool o action_id confirmado.")
    confirmed: Literal[True]
    approved_by: str = Field(min_length=1, description="Id del usuario humano que confirma.")
    approved_by_role: str
    reason: str = Field(min_length=5, max_length=300)
    confirmed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class ToolCallVerdict:
    tool: str
    allowed: bool
    kind: ToolKind | None = None
    reason: RejectReason | None = None
    detail: str = ""
    findings: tuple[str, ...] = field(default_factory=tuple)


def _confirmation_problem(tool_name: str, confirmation: HumanConfirmation | None) -> str | None:
    if confirmation is None:
        return "sin confirmación humana"
    action = IRREVERSIBLE_TOOLS.get(tool_name)
    if confirmation.action not in {tool_name, action.action_id if action else tool_name}:
        return "la confirmación es de otra acción"
    if confirmation.approved_by_role not in STAFF_ROLES:
        return "quien confirma no es personal de TrackFlow"
    if confirmation.approved_by.strip().lower() in {"agent", "agente", "system", "llm"}:
        return "el agente no puede confirmarse a sí mismo"
    return None


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _reject(tool_name: str, kind: ToolKind | None, reason: RejectReason, detail: str,
            findings: tuple[str, ...] = ()) -> ToolCallVerdict:
    events.record(
        guard="tool_call", category=reason, failure_type="security", action="block",
        rules=[tool_name, *findings], detail=detail,
    )
    return ToolCallVerdict(tool_name, False, kind, reason, detail, findings)


def validate_tool_call(
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    confirmation: HumanConfirmation | None = None,
) -> ToolCallVerdict:
    """¿Se puede ejecutar `tool_name(arguments)`? Nunca lanza; el rechazo va en el veredicto."""
    arguments = arguments or {}
    kind = tool_kind(tool_name)
    if kind is None:
        return _reject(tool_name, None, "unknown_tool", f"la tool {tool_name!r} no está en el catálogo")

    if kind in ("write", "irreversible"):
        problem = _confirmation_problem(tool_name, confirmation)
        if problem:
            reason: RejectReason = "human_confirmation_required" if confirmation is None else "invalid_confirmation"
            action = IRREVERSIBLE_TOOLS.get(tool_name)
            label = f"{action.action_id} (BRIEFING {action.briefing})" if action else "tool de escritura"
            return _reject(tool_name, kind, reason, f"{label}: {problem}")
        return ToolCallVerdict(tool_name, True, kind)

    try:
        READ_TOOLS[tool_name].model_validate(arguments)
    except ValidationError as exc:
        fields = ",".join(".".join(str(part) for part in error["loc"]) or "-" for error in exc.errors())
        return _reject(tool_name, kind, "invalid_arguments", f"argumentos fuera de contrato: {fields}")

    findings: list[str] = []
    for text in _strings(arguments):
        if ROLE_MARKERS.search(text):
            findings.append("role_markers")
        findings.extend(injection_rules(text))
    if findings:
        return _reject(tool_name, kind, "instruction_in_arguments", "un argumento tiene forma de instrucción",
                       tuple(sorted(set(findings))))
    return ToolCallVerdict(tool_name, True, kind)


# Útil para documentar: qué tool corresponde a cada acción del BRIEFING.
def irreversible_catalog() -> list[dict[str, Any]]:
    return [
        {"action_id": a.action_id, "briefing": a.briefing, "description": a.description,
         "tools": list(a.tools), "control": a.control}
        for a in IRREVERSIBLE_ACTIONS
    ]
