"""Enrutador del agente: decide si la pregunta necesita el RAG, una tool o varias.

Enrutador híbrido:

1. **LLM** (`classify_with_llm`): el modelo de generación (`LLM_MODEL`) lee la
   pregunta y devuelve un JSON con la decisión. Se valida contra el contrato
   `RouteDecision` (y, dentro, `TicketQuery` / `InventoryQuery`).
2. **Guardas de anclaje**: un id de ticket, un SKU o un nombre de producto que
   el LLM proponga y que **no aparezca en la pregunta** invalida la decisión.
   El agente nunca consulta un recurso que el usuario no ha mencionado.
3. **Reglas** (`classify_with_rules`): si el LLM falla, tarda, devuelve algo
   no válido o no pasa las guardas, decide un clasificador por patrones.

El usuario nunca indica qué fuente usar: la decisión sale del contenido de la
pregunta, y queda registrada en el trace (`decided_by` y `reason`).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from data.pipelines import rag as rag_pipeline
from packages.shared.incident_validation import IncidentBranch, IncidentCategory, IncidentStatus

from .tools import InventoryQuery, TicketQuery, fold

logger = logging.getLogger("agent.routing")

ROUTER_TIMEOUT_SECONDS = 15.0


class RouteDecision(BaseModel):
    """Qué fuentes necesita la pregunta. Si no necesita ninguna tool, usa el RAG."""

    model_config = ConfigDict(extra="forbid")

    needs_rag: bool = True
    ticket: TicketQuery | None = None
    inventory: InventoryQuery | None = None
    reason: str = ""
    decided_by: Literal["llm", "rules"] = "rules"

    @model_validator(mode="after")
    def _at_least_one_source(self) -> "RouteDecision":
        if not self.needs_rag and self.ticket is None and self.inventory is None:
            self.needs_rag = True
        return self

    @property
    def sources(self) -> list[str]:
        planned = []
        if self.ticket is not None:
            planned.append("incidents")
        if self.inventory is not None:
            planned.append("inventory")
        if self.needs_rag:
            planned.append("rag")
        return planned


# --------------------------------------------------------------------------- #
# Reglas
# --------------------------------------------------------------------------- #
_fold = fold  # minúsculas y sin tildes, para comparar patrones


TICKET_WORD = re.compile(r"\b(tickets?|incidencias?|incidentes?|incidents?|reclamacion(?:es)?)\b")
TICKET_ID = re.compile(
    r"\b(?:tickets?|incidencias?|incidentes?|incidents?|reclamacion(?:es)?)\s*"
    r"(?:n[o°º]\.?\s*|numero\s*|#\s*|id\s*)?(\d{1,7})\b"
)
HASH_ID = re.compile(r"#\s*(\d{1,7})\b")
TICKET_LOOKUP = re.compile(r"\b(estado|cuant[oa]s|cuales|lista|listar|muestrame|ensename|hay|tengo|tenemos|ver)\b")
TICKET_STATUS = {
    IncidentStatus.open: re.compile(r"\b(abiert[oa]s?|pendientes?|open)\b"),
    IncidentStatus.in_progress: re.compile(r"\b(en curso|en progreso|en proceso|in progress)\b"),
    IncidentStatus.resolved: re.compile(r"\b(resuelt[oa]s?|cerrad[oa]s?|resolved)\b"),
    IncidentStatus.discarded: re.compile(r"\b(descartad[oa]s?|discarded)\b"),
}
TICKET_BRANCH = {
    IncidentBranch.zaragoza: re.compile(r"\bzaragoza\b"),
    IncidentBranch.los_angeles: re.compile(r"\blos angeles\b"),
    IncidentBranch.central: re.compile(r"\bcentral\b"),
}
TICKET_CATEGORY = {
    IncidentCategory.damage: re.compile(r"\b(danad[oa]s?|roto?s?|damage)\b"),
    IncidentCategory.delayed_delivery: re.compile(r"\b(retras\w*|delayed)\b"),
    IncidentCategory.wrong_address: re.compile(r"\bdireccion (erronea|incorrecta|equivocada)\b"),
    IncidentCategory.lost_parcel: re.compile(r"\b(perdid[oa]s?|extraviad[oa]s?|lost)\b"),
    IncidentCategory.return_request: re.compile(r"\b(solicitud(?:es)? de devolucion)\b"),
}
INVENTORY_WORD = re.compile(r"\b(stock|inventario|existencias|unidades|disponibilidad)\b")
SKU_LABELLED = re.compile(r"\bSKU[\s:#-]*([A-Za-z0-9][A-Za-z0-9_-]{1,63})", re.IGNORECASE)
SKU_CODE = re.compile(r"\b([A-Z]{2,}[A-Z0-9]*-[A-Z0-9][A-Z0-9-]*)\b")
PRODUCT_AFTER = re.compile(r"\b(?:stock|existencias|unidades|inventario|disponibilidad)\s+(?:hay\s+)?(?:de|del)\s+(.+)$")
LEADING_ARTICLE = re.compile(r"^(?:la|el|los|las|un|una|unos|unas|producto|productos)\s+")
POLICY_WORD = re.compile(
    r"\b(politica|plazo|ventana|sla|tarifa|precio|coste|cuesta|procedimiento|que hago|como se|"
    r"garantiz\w*|cobertura|reembolso|devolucion estandar|condiciones)\b"
)


def _ticket_query(question: str, folded: str) -> TicketQuery | None:
    match = TICKET_ID.search(folded) or HASH_ID.search(folded)
    if match:
        return TicketQuery(ticket_id=int(match.group(1)))
    # Sin id, solo es consulta de datos si pide ver/contar tickets y no es una pregunta de política.
    if not TICKET_WORD.search(folded) or POLICY_WORD.search(folded):
        return None
    if not (TICKET_LOOKUP.search(folded) or any(p.search(folded) for p in TICKET_STATUS.values())):
        return None
    filters = {}
    for value, pattern in TICKET_STATUS.items():
        if pattern.search(folded):
            filters["status"] = value
            break
    for value, pattern in TICKET_BRANCH.items():
        if pattern.search(folded):
            filters["branch"] = value
            break
    for value, pattern in TICKET_CATEGORY.items():
        if pattern.search(folded):
            filters["category"] = value
            break
    return TicketQuery(**filters)


def _inventory_query(question: str, folded: str) -> InventoryQuery | None:
    labelled = SKU_LABELLED.search(question)
    code = labelled or SKU_CODE.search(question)
    if code:
        return InventoryQuery(sku=code.group(1))
    if not INVENTORY_WORD.search(folded):
        return None
    after = PRODUCT_AFTER.search(folded.strip(" ¿?¡!."))
    if not after:
        return None
    # Nombre sin tildes: la tool compara también sin tildes («cartón» = «carton»).
    name = LEADING_ARTICLE.sub("", after.group(1).strip(" ¿?¡!.,"))
    return InventoryQuery(product_name=name) if len(name) >= 2 else None


def classify_with_rules(question: str, *, reason: str = "") -> RouteDecision:
    folded = _fold(question)
    ticket = _ticket_query(question, folded)
    inventory = _inventory_query(question, folded)
    uses_tool = ticket is not None or inventory is not None
    needs_rag = not uses_tool or bool(POLICY_WORD.search(folded))
    return RouteDecision(
        needs_rag=needs_rag,
        ticket=ticket,
        inventory=inventory,
        reason=reason or "Clasificación por reglas",
        decided_by="rules",
    )


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #
ROUTER_PROMPT = """Eres el enrutador del agente de soporte de TrackFlow (logística en Los Ángeles y Zaragoza).
Decide qué fuentes necesita la pregunta del usuario. No la respondas.

Fuentes:
- "rag": base de conocimiento estable (políticas de devoluciones, SLA de entrega, transportistas, tarifas de almacenaje).
- "ticket": gestor de incidentes en tiempo real (estado y datos de tickets/incidencias). Filtros válidos:
  ticket_id (entero), status (open, in_progress, resolved, discarded),
  category (RETURN_REQUEST, DAMAGE, DELAYED_DELIVERY, WRONG_ADDRESS, LOST_PARCEL),
  origin (customer, branch, internal), branch ("Los Angeles", "Zaragoza", "central").
- "inventory": gestor de inventario en tiempo real (stock de un producto). Campos: sku o product_name.

Reglas:
- Una pregunta sobre políticas o procedimientos usa solo "rag", aunque mencione tickets, sucursales o productos en general.
- Una pregunta por el estado o los datos de tickets concretos usa "ticket"; por stock de un producto, "inventory".
- Si pide datos en vivo y además una política, usa la tool y "rag".
- Nunca inventes ids, SKU ni nombres de producto: cópialos literalmente de la pregunta.

Responde SOLO con un objeto JSON, sin texto alrededor:
{"needs_rag": true|false, "ticket": null | {"ticket_id": null, "status": null, "category": null, "origin": null, "branch": null},
 "inventory": null | {"sku": null, "product_name": null}, "reason": "una frase"}"""

JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class RouteRejected(ValueError):
    """La decisión del LLM no es válida o no está anclada en la pregunta."""


def _strip_nulls(value):
    if isinstance(value, dict):
        return {key: _strip_nulls(item) for key, item in value.items() if item is not None}
    return value


def parse_llm_decision(text: str, question: str) -> RouteDecision:
    match = JSON_OBJECT.search(text or "")
    if not match:
        raise RouteRejected("el LLM no devolvió JSON")
    try:
        raw = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise RouteRejected(f"JSON inválido: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise RouteRejected("el JSON no es un objeto")
    raw = _strip_nulls(raw)  # {"ticket": {}} = listar tickets sin filtros
    if raw.get("inventory") == {}:
        raw.pop("inventory")  # inventario sin SKU ni nombre: no hay nada que consultar
    raw.pop("decided_by", None)
    try:
        decision = RouteDecision.model_validate({**raw, "decided_by": "llm"})
    except ValidationError as exc:
        raise RouteRejected(f"contrato no válido: {exc.error_count()} errores") from exc

    folded = _fold(question)
    if decision.ticket and decision.ticket.ticket_id is not None:
        if not re.search(rf"(?<!\d){decision.ticket.ticket_id}(?!\d)", question):
            raise RouteRejected(f"ticket_id {decision.ticket.ticket_id} no aparece en la pregunta")
    if decision.inventory and decision.inventory.sku and decision.inventory.sku.lower() not in question.lower():
        raise RouteRejected(f"SKU {decision.inventory.sku!r} no aparece en la pregunta")
    if (
        decision.inventory
        and decision.inventory.product_name
        and _fold(decision.inventory.product_name) not in folded
    ):
        raise RouteRejected(f"producto {decision.inventory.product_name!r} no aparece en la pregunta")
    return decision


def classify_with_llm(question: str) -> RouteDecision:
    settings = rag_pipeline.load_settings()
    rag_pipeline.check_models(settings)
    completion = rag_pipeline.get_generation_client().chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": ROUTER_PROMPT},
            {"role": "user", "content": question},
        ],
        temperature=0.0,
        timeout=ROUTER_TIMEOUT_SECONDS,
    )
    return parse_llm_decision(completion.choices[0].message.content or "", question)


def decide_route(question: str) -> RouteDecision:
    """LLM primero; reglas si el LLM falla o su decisión no es válida."""
    try:
        return classify_with_llm(question)
    except Exception as exc:  # LLM caído, timeout, JSON inválido, guarda de anclaje…
        logger.warning("Enrutador LLM descartado (%s): uso reglas", exc)
        return classify_with_rules(question, reason=f"Reglas (LLM descartado: {type(exc).__name__}: {str(exc)[:120]})")
