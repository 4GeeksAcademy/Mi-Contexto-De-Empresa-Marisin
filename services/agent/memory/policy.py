"""Qué puede recordar el agente y qué nunca (company-BRIEFING de TrackFlow, Hito 8).

El modelo **propone**; esta política **decide** si la propuesta puede llegar al
usuario. Es código determinista a propósito: un mensaje malicioso puede
convencer al LLM, pero no a una expresión regular ni a una lista cerrada.

Se puede recordar (y nada más):

* `carrier_rule` — reglas de asignación de carrier corregidas (cobertura de una
  zona, una ruta que un carrier dejó de operar).
* `known_incident` — contexto de incidentes conocidos y recurrentes de una zona
  (p. ej. una huelga), para no re-escalar la misma alerta.
* `b2b_report_preference` — preferencias de un cliente B2B sobre su reporte mensual.

Nunca se recuerda, lo pida quien lo pida:

* **Ubicación exacta de clientes, B2C (destinatarios) y B2B (marcas)**:
  direcciones, códigos postales, coordenadas, "vive en…", "su almacén está en…".
* **Rutas internas y seguridad física del almacén**: pasillos, estanterías,
  muelles, códigos de acceso, turnos de vigilancia.
* **Incidencias puntuales de un solo paquete** sin patrón: tracking, "el paquete…",
  número de pedido.
* **Contratos comerciales en negociación** (los lleva el CRM de Miguel Torres).
* Además (buenas prácticas): datos personales de contacto y texto con forma de
  instrucción para el modelo (inyección de prompt).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import CARRIER_ALIASES, CARRIERS_BY_COUNTRY, Actor, MemoryCategory, MemoryDraft, fold

# Quién puede sustituir una regla que aprobó OTRA persona (anti-envenenamiento).
SUPERSEDE_ROLES = {"admin", "manager"}
MAX_APPROVED_PER_USER_PER_DAY = 10

# --------------------------------------------------------------------------- #
# Detectores (sobre texto plegado: minúsculas y sin tildes)
# --------------------------------------------------------------------------- #
STREET = (
    r"(?:calle|c/|avenida|avda\.?|av\.|paseo|plaza|pza\.?|ronda|travesia|"
    r"poligono|street|st\.|avenue|ave\.|road|rd\.|boulevard|blvd\.?|drive|dr\.|lane|ln\.|suite|apt\.?|apartment)"
)
FORBIDDEN_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    # B2C y B2B: cualquier dirección, CP, coordenada o referencia al domicilio/ubicación de un cliente.
    "customer_location": (
        re.compile(rf"\b{STREET}\s+[\w .'-]{{0,40}}?\d{{1,5}}"),
        re.compile(r"\b\d{1,5}\s+[a-z][\w.'-]*(?:\s+[a-z][\w.'-]*){0,3}\s+(?:street|st|avenue|ave|road|rd|blvd|drive|dr|lane|ln|way)\b"),
        re.compile(rf"\b{STREET}\s+(?:de\s+)?[a-z]"),
        re.compile(r"\b(?:portal|piso|escalera|puerta)\s+\d"),
        re.compile(r"\b\d{1,2}\s*[ºª°]\s*[a-z]?\b"),
        re.compile(r"(?<![\w-])\d{5}(?:-\d{4})?(?![\w-])"),  # código postal ES / ZIP US
        re.compile(r"-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}"),  # coordenadas
        re.compile(
            r"\b(?:direccion|domicilio|vive en|reside en|su casa|address|lives at|home of)\b"
            r"|\b(?:almacen|oficina|nave|sede|bodega|warehouse)\s+(?:del?|de la)\s+(?:cliente|marca)\b"
            r"|\b(?:el|la|del|de la)\s+(?:cliente|destinatari[oa]|marca)\s+(?:esta|vive|tiene su (?:almacen|oficina|nave))\b"
        ),
    ),
    "warehouse_internal": (
        re.compile(
            r"\b(?:pasillos?|estanterias?|estantes?|racks?|baldas?|muelles? de carga|aisles?|"
            r"ubicacion(?:es)? interna|zona de picking|ruta(?:s)? (?:interna|de picking)|"
            r"camaras? de seguridad|codigo de (?:acceso|alarma|puerta)|alarma|puerta trasera|"
            r"turnos? de (?:vigilancia|seguridad)|vigilante|caja fuerte)\b"
        ),
    ),
    "single_shipment": (
        re.compile(
            r"\b(?:tracking|numero de seguimiento|n[o°º]\.? de seguimiento|"
            r"(?:este|ese) (?:paquete|envio)|el paquete (?:con|del?|n)|pedido\s*(?:n[o°º]\.?|#|numero)?\s*\d+|"
            r"order\s*#?\s*\d+|albaran)\b"
        ),
    ),
    "commercial_contract": (
        re.compile(
            r"\b(?:contratos?|negociacion|negociando|negociar|renovacion|renovar el contrato|precio pactado|"
            r"tarifa negociada|descuentos?|oferta comercial|propuesta comercial|clausulas?|rfp|penalizacion)\b"
        ),
    ),
    "personal_data": (
        re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
        re.compile(r"(?<![\d-])(?:\+\d{1,3}[\s.-]?)?(?:\d[\s.-]?){8,11}\d(?![\d-])"),
        re.compile(r"\b(?:dni|nie|nif|pasaporte|ssn|iban|tarjeta)\b"),
    ),
    "instruction_like": (
        re.compile(
            r"\b(?:ignora|ignore|olvida (?:las|tus|todas)|system prompt|prompt|a partir de ahora|"
            r"siempre (?:responde|di|contesta)|nunca (?:menciones|digas)|eres un|you are now|instrucciones?|"
            r"jailbreak|desactiva|sin restricciones)\b"
        ),
    ),
}
# Códigos de tracking en el texto original (letras + números, p. ej. XJ4471, 1Z999AA1…).
TRACKING_CODE = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,}\b")

REASON_TEXT = {
    "customer_location": "contiene la ubicación de un cliente (B2C o B2B)",
    "warehouse_internal": "contiene rutas internas o seguridad física del almacén",
    "single_shipment": "es una incidencia puntual de un solo envío",
    "commercial_contract": "trata un contrato comercial (lo gestiona el CRM)",
    "personal_data": "contiene datos personales de contacto",
    "instruction_like": "tiene forma de instrucción para el modelo",
}


def forbidden_reasons(text: str) -> list[str]:
    """Códigos de los datos prohibidos que aparecen en `text` (lista vacía si no hay)."""
    folded = fold(text)
    reasons = [code for code, patterns in FORBIDDEN_PATTERNS.items() if any(p.search(folded) for p in patterns)]
    if TRACKING_CODE.search(text or "") and "single_shipment" not in reasons:
        reasons.append("single_shipment")
    return reasons


REDACT_CODES = ("customer_location", "warehouse_internal", "personal_data")


def redact(text: str | None, limit: int = 500) -> str:
    """Copia del mensaje apta para el registro de auditoría.

    Si el mensaje contiene una ubicación de cliente, una ruta interna del almacén
    o datos de contacto, **no se guarda nada de su texto**: solo qué tipo de dato
    tenía. Los códigos de tracking se sustituyen en línea. Así el log demuestra
    qué pasó sin persistir lo que el BRIEFING prohíbe recordar.
    """
    value = (text or "")[:limit]
    found = [code for code in forbidden_reasons(value) if code in REDACT_CODES]
    if found:
        return f"[mensaje redactado: contiene {', '.join(found)}]"
    return TRACKING_CODE.sub("[REDACTADO]", value)


# --------------------------------------------------------------------------- #
# Veredicto
# --------------------------------------------------------------------------- #
@dataclass
class PolicyVerdict:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    @property
    def explanation(self) -> str:
        return "; ".join(REASON_TEXT.get(code, code) for code in self.reasons)


def _mentions(folded_message: str, value: str | None) -> bool:
    """Todas las palabras significativas de `value` aparecen en el mensaje."""
    words = [w for w in re.findall(r"[a-z0-9]+", fold(value)) if len(w) >= 3 and w not in {"del", "las", "los", "una"}]
    return bool(words) and all(w in folded_message for w in words)


def _carrier_mentioned(folded_message: str, carrier: str) -> bool:
    return any(alias in folded_message for alias in CARRIER_ALIASES[carrier])


def check_draft(draft: MemoryDraft, *, message: str) -> PolicyVerdict:
    """¿Puede proponerse `draft` al usuario? `message` es el mensaje del usuario que lo originó."""
    reasons: list[str] = []
    text = " ".join(filter(None, [draft.fact, draft.zone, draft.client, draft.reason]))
    reasons.extend(forbidden_reasons(text))
    # El mensaje de origen también cuenta: si trae una dirección, una ruta interna, un contrato,
    # un solo paquete o una instrucción, no se propone nada aunque el modelo lo haya "limpiado".
    reasons.extend(forbidden_reasons(message))
    if "?" in draft.fact:
        reasons.append("not_a_statement")

    folded_message = fold(message)
    category = draft.category
    if category is MemoryCategory.carrier_rule:
        if not draft.carrier or not draft.country:
            reasons.append("missing_scope")
        elif draft.carrier not in CARRIERS_BY_COUNTRY[draft.country.value]:
            reasons.append("carrier_not_in_country")
        elif not _carrier_mentioned(folded_message, draft.carrier):
            reasons.append("not_grounded")
    elif category is MemoryCategory.known_incident:
        if not draft.country or not draft.zone:
            reasons.append("missing_scope")
        elif not _mentions(folded_message, draft.zone):
            reasons.append("not_grounded")
    elif category is MemoryCategory.b2b_report_preference:
        if not draft.client:
            reasons.append("missing_scope")
        elif not _mentions(folded_message, draft.client):
            reasons.append("not_grounded")
        elif not re.search(r"\b(reporte|report|informe)\b", fold(draft.fact)):
            reasons.append("not_a_report_preference")

    # Una zona que se nombra en la propuesta tiene que venir del mensaje (el LLM no la inventa).
    if draft.zone and category is MemoryCategory.carrier_rule and not _mentions(folded_message, draft.zone):
        reasons.append("not_grounded")
    return PolicyVerdict(allowed=not reasons, reasons=sorted(set(reasons)))


def check_edited_fact(fact: str) -> PolicyVerdict:
    """Una edición del usuario pasa por los mismos detectores que la propuesta original."""
    reasons = forbidden_reasons(fact)
    if len(fact.strip()) < 10:
        reasons.append("too_short")
    return PolicyVerdict(allowed=not reasons, reasons=sorted(set(reasons)))


def may_supersede(actor: Actor, previous_author: int | None) -> bool:
    """Sustituir una regla aprobada por otra persona exige rol admin o manager."""
    return previous_author is None or previous_author == actor.user_id or actor.role in SUPERSEDE_ROLES
