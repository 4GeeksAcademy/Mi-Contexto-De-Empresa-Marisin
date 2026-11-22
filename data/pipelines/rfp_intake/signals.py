"""Señales deterministas del texto de una RFP (respaldo y guardas de los agentes).

Cada agente LLM tiene un respaldo por reglas que sale de aquí, y las guardas que
validan al LLM también las usan:

- `detect_services()`: servicios pedidos **y servicios excluidos explícitamente**
  («mantenemos nuestro propio transportista», «not required»). Una exclusión
  explícita gana siempre: ModaViva nunca activa `lastmile`.
- `detect_country()`: Estados Unidos o España (define la moneda).
- `proposal_cues()` / `vendor_cues()`: ¿alguien pide una propuesta a TrackFlow,
  o alguien le vende algo a TrackFlow (pitch de transportista)?
- `find_monthly_volume()`, `find_deadline()`, `find_budget()`, `find_client_name()`,
  `find_contact()`: metadatos literales, nunca estimados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .config import COUNTRY_ES, COUNTRY_US, SERVICES
from .text import blocks, clauses, fold

# --------------------------------------------------------------------------- #
# Servicios
# --------------------------------------------------------------------------- #
SERVICE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "warehousing": (
        "almacenamiento", "almacen", "warehous", "storage", "fulfillment", "fulfilment",
        "sku", "pallet", "palet", "inventario", "inventory",
    ),
    "last_mile": (
        "ultima milla", "last mile", "last-mile", "reparto", "shipping", "envio", "carrier",
        "transportista", "delivery", "deliveries", "entregas", "paqueteria",
    ),
    "reverse_logistics": (
        "devolucion", "returns", "reverse logistics", "logistica inversa", "reacondicionamiento",
        "restock", "refurbish",
    ),
}
# Palabras que además llevan un extracto al worker (no activan el servicio solas).
EXCERPT_EXTRA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "warehousing": ("erp", "integracion", "integration", "api", "onboarding", "capacidad", "capacity", "3pl"),
    "last_mile": ("destino", "destination", "across the us", "sla", "plazo de entrega", "delivery time"),
    "reverse_logistics": ("inspeccion", "inspection", "return rate", "tasa de devolucion"),
}
NEGATION_CUES = (
    "no se requiere", "no requerimos", "no necesitamos", "no se necesita", "no incluye",
    "not required", "not needed", "no need for", "we don't need", "we do not need",
    "propio transportista", "own carrier", "our own shipping", "excluye", "excluding",
    "excluded", "fuera del alcance", "out of scope",
)

# Peticiones que ningún departamento de la propuesta cubre (pregunta de diseño 1).
UNASSIGNED_KEYWORDS: dict[str, tuple[str, ...]] = {
    "aduanas / comercio exterior": ("aduana", "customs", "importacion", "import duties", "despacho aduanero"),
    "transporte internacional / carga": ("freight", "flete", "ocean", "maritimo", "air cargo", "carga aerea"),
    "marketing / diseño de packaging": ("marketing", "packaging design", "diseno de packaging", "branding"),
    "atención al cliente / call center": ("call center", "customer service", "atencion al cliente"),
    "seguros de mercancía": ("insurance", "seguro de mercancia", "seguros"),
}


def _keyword_regex(keyword: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(keyword))


_COMPILED: dict[str, re.Pattern[str]] = {}


def has_keyword(folded_text: str, keyword: str) -> bool:
    pattern = _COMPILED.get(keyword)
    if pattern is None:
        pattern = _COMPILED[keyword] = _keyword_regex(keyword)
    return bool(pattern.search(folded_text))


def mentions(folded_text: str, keywords: tuple[str, ...]) -> bool:
    return any(has_keyword(folded_text, keyword) for keyword in keywords)


def is_negated(folded_clause: str) -> bool:
    return any(cue in folded_clause for cue in NEGATION_CUES)


@dataclass
class ServiceSignals:
    requested: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    exclusion_evidence: dict[str, list[str]] = field(default_factory=dict)


def detect_services(markdown: str) -> ServiceSignals:
    """Servicios pedidos y excluidos, cláusula a cláusula."""
    positive: dict[str, list[str]] = {service: [] for service in SERVICES}
    negative: dict[str, list[str]] = {service: [] for service in SERVICES}
    for block in blocks(markdown):
        for clause in clauses(block):
            folded = fold(clause)
            for service, keywords in SERVICE_KEYWORDS.items():
                if mentions(folded, keywords):
                    (negative if is_negated(folded) else positive)[service].append(clause)
    excluded = [service for service in SERVICES if negative[service]]
    requested = [service for service in SERVICES if positive[service] and service not in excluded]
    return ServiceSignals(
        requested=requested,
        excluded=excluded,
        evidence={service: positive[service] for service in requested},
        exclusion_evidence={service: negative[service] for service in excluded},
    )


def detect_unassigned(markdown: str) -> list[dict[str, str]]:
    """Peticiones fuera de los tres departamentos, con su cita."""
    found: list[dict[str, str]] = []
    for block in blocks(markdown):
        folded = fold(block)
        for topic, keywords in UNASSIGNED_KEYWORDS.items():
            if mentions(folded, keywords) and not is_negated(folded) and topic not in {item["topic"] for item in found}:
                found.append({"topic": topic, "evidence": block[:300]})
    return found


# --------------------------------------------------------------------------- #
# ¿RFP o pitch de un proveedor?
# --------------------------------------------------------------------------- #
FORMAL_CUES = ("request for proposal", "rfp", "solicitud de propuesta", "pliego", "licitacion")
PROPOSAL_CUES = FORMAL_CUES + (
    "proposal", "propuesta", "cotizacion", "quote", "quotation", "presupuesto",
    "3pl partner", "looking for a 3pl", "partner logistico", "buscamos un partner",
    "we need someone to handle", "necesitamos un operador",
)
VENDOR_CUES = (
    "for trackflow", "trackflow's", "a trackflow", "partner with trackflow", "become one of",
    "preferred carrier", "carrier partner", "partnership", "introductory rates",
    "exclusive shipping rates", "currently offering", "we are offering", "ofrecemos tarifas",
    "nuestras tarifas", "tarifas exclusivas", "go over pricing", "our rates", "our pricing",
)


def _cues(folded_text: str, cues: tuple[str, ...]) -> list[str]:
    return [cue for cue in cues if has_keyword(folded_text, cue)]


def proposal_cues(markdown: str) -> list[str]:
    return _cues(fold(markdown), PROPOSAL_CUES)


def vendor_cues(markdown: str) -> list[str]:
    return _cues(fold(markdown).replace("’", "'"), VENDOR_CUES)


def is_formal(markdown: str) -> bool:
    return bool(_cues(fold(markdown), FORMAL_CUES))


# --------------------------------------------------------------------------- #
# País
# --------------------------------------------------------------------------- #
_SPAIN_PATTERNS = (
    r"\bespana\b", r"\bspain\b", r"\bespanol", r"\bspanish\b", r"\bzaragoza\b", r"\bmadrid\b",
    r"\bbarcelona\b", r"\bvalencia\b", r"\bs\.l\.", r"\bs\.a\.", r"[a-z0-9]\.es\b", r"\beur\b", "€", r"\beuros?\b",
)
_US_PATTERNS = (
    r"\busa\b", r"\bunited states\b", r"\bu\.s\.", r"\blos angeles\b", r",\s*ca\b", r"\bcalifornia\b",
    r"\bnew york\b", r"\bacross the us\b", r"\btexas\b", r"\$", r"\busd\b", r"\bdollars?\b",
)


def detect_country(markdown: str) -> tuple[str | None, dict[str, int]]:
    folded = fold(markdown)
    spain = sum(bool(re.search(pattern, folded)) for pattern in _SPAIN_PATTERNS)
    us = sum(bool(re.search(pattern, folded)) for pattern in _US_PATTERNS)
    us += bool(re.search(r"\bLA\b", markdown or ""))  # «out of LA» (mayúsculas: no es el artículo)
    scores = {COUNTRY_ES: spain, COUNTRY_US: us}
    if spain == us:
        return None, scores
    return (COUNTRY_ES if spain > us else COUNTRY_US), scores


# --------------------------------------------------------------------------- #
# Volumen, fechas, presupuesto
# --------------------------------------------------------------------------- #
_VOLUME_PATTERNS = (
    re.compile(
        r"(\d[\d.,]*\s?k?)\s*\+?\s*(?:orders|pedidos|envios|shipments|packages|paquetes|parcels)"
        r"\s*(?:a|per|al|por|cada|/|each)?\s*(?:month|mes)\b"
    ),
    re.compile(r"(\d[\d.,]*\s?k?)\s*(?:orders|pedidos|envios|shipments)\s*(?:mensuales|monthly)\b"),
    re.compile(r"(?:monthly|mensual(?:es)?)\s*(?:volume|volumen|orders|pedidos)\D{0,20}(\d[\d.,]*\s?k?)"),
)


def _to_int(raw: str) -> int | None:
    value = raw.strip().lower()
    multiplier = 1000 if value.endswith("k") else 1
    value = value.rstrip("k").strip()
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", value):
        value = re.sub(r"[.,]", "", value)
    try:
        return int(float(value.replace(",", ".")) * multiplier)
    except ValueError:
        return None


def find_monthly_volume(markdown: str) -> tuple[int | None, str | None]:
    folded = fold(markdown)
    for pattern in _VOLUME_PATTERNS:
        match = pattern.search(folded)
        if match:
            return _to_int(match.group(1)), match.group(0)
    return None, None


MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12, "ene": 1, "abr": 4, "ago": 8, "dic": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_DATE_EN = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b")
_DATE_ES = re.compile(rf"\b(\d{{1,2}})\s+(?:de\s+)?({_MONTH_ALT})\.?\s+(?:de\s+)?(\d{{4}})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DEADLINE_LABEL = re.compile(
    r"(proposal due date|due date|deadline|fecha limite(?: de (?:entrega|presentacion))?|plazo de presentacion)\s*[:\-]?\s*"
)
_GO_LIVE = re.compile(
    r"((?:up and running|go[- ]live|start|arrancar|empezar|operativos)[^.\n]{0,80}?"
    r"(?:around|by|before|antes del?|hacia el)\s+[a-z]+\.?\s+\d{1,2}(?:st|nd|rd|th)?\)?)",
    re.IGNORECASE,
)
_RELATIVE = re.compile(r"(within the next \d+ (?:days|weeks)|en las próximas \d+ semanas)", re.IGNORECASE)


def parse_date(folded_text: str) -> date | None:
    for pattern, order in ((_DATE_ISO, "ymd"), (_DATE_EN, "mdy"), (_DATE_ES, "dmy")):
        match = pattern.search(folded_text)
        if not match:
            continue
        try:
            if order == "ymd":
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            if order == "mdy":
                return date(int(match.group(3)), MONTHS[match.group(1)], int(match.group(2)))
            return date(int(match.group(3)), MONTHS[match.group(2)], int(match.group(1)))
        except (KeyError, ValueError):
            continue
    return None


def find_deadline(markdown: str) -> tuple[date | None, str | None]:
    """Fecha límite etiquetada; si solo hay una fecha sin año, se guarda el texto."""
    for line in (markdown or "").splitlines():
        folded = fold(line)
        label = _DEADLINE_LABEL.search(folded)
        if label:
            parsed = parse_date(folded[label.end():])
            if parsed:
                return parsed, line.strip()
    flat = re.sub(r"\s+", " ", markdown or "")
    go_live = _GO_LIVE.search(flat)
    if go_live:
        return None, go_live.group(1)
    relative = _RELATIVE.search(flat)
    if relative:
        return None, relative.group(1)
    return None, None


_BUDGET = re.compile(
    r"(?:budget|presupuesto(?: de referencia| maximo| estimado)?)[^.\n]{0,40}?"
    r"((?:[$€]\s?)?\d[\d.,]*\s?(?:k|usd|eur|€|euros|dollars)?"
    r"(?:\s?(?:-|–|to|a|y)\s?(?:[$€]\s?)?\d[\d.,]*\s?(?:k|usd|eur|€|euros|dollars)?)?)"
)


def find_budget(markdown: str) -> str | None:
    match = _BUDGET.search(fold(markdown))
    if not match or not re.search(r"\d", match.group(1)):
        return None
    return match.group(1).strip()


# --------------------------------------------------------------------------- #
# Cliente y contacto
# --------------------------------------------------------------------------- #
_LEGAL_SUFFIX = re.compile(r",?\s+(?:S\.L(?:\.U)?\.?|S\.A\.?|Inc\.?|LLC|Ltd\.?|Corp\.?)$", re.IGNORECASE)
_NAME = r"([A-Z][\w&'’.-]*(?:\s+[A-Z][\w&'’.-]*){0,3})"
_CLIENT_PATTERNS = (
    re.compile(r"(?:Issuing Organization|Organización emisora|Cliente|Client|Company|Empresa)\s*:\s*(.+)"),
    re.compile(rf"^{_NAME}\s+[—–-]\s+.+$", re.MULTILINE),
    re.compile(rf"\b(?:We(?:'|’)re|We are|Somos)\s+{_NAME}\s*,"),
)
_SIGNATURE_OPENERS = re.compile(r"^(?:best|best regards|regards|kind regards|thanks|saludos|un saludo|atentamente)[,.!]?$", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _clean_client(name: str) -> str:
    cleaned = _LEGAL_SUFFIX.sub("", name.strip())
    return cleaned.strip(" ,.")


def find_client_name(markdown: str) -> str | None:
    for pattern in _CLIENT_PATTERNS:
        match = pattern.search(markdown or "")
        if match:
            name = _clean_client(match.group(1))
            if 1 < len(name) <= 80 and not name.lower().startswith(("subject", "asunto", "request")):
                return name
    return None


def find_contact(markdown: str) -> dict[str, str | None]:
    lines = [line.strip() for line in (markdown or "").splitlines() if line.strip()]
    name = role = None
    for index, line in enumerate(lines):
        folded = fold(line)
        is_contact_heading = re.fullmatch(r"(?:\d+[.)]\s*)?(?:contact|contacto)", folded)
        if is_contact_heading or _SIGNATURE_OPENERS.match(line):
            if index + 1 < len(lines):
                name = lines[index + 1]
            if index + 2 < len(lines) and len(lines[index + 2]) <= 80:
                role = lines[index + 2]
    email_match = _EMAIL.search(markdown or "")
    if name and (len(name) > 60 or _EMAIL.search(name)):
        name = None
    return {"name": name, "role": role, "email": email_match.group(0) if email_match else None}
