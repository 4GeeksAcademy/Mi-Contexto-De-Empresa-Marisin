"""Validación de la salida antes de devolverla al usuario (última capa).

Se aplica a la respuesta COMPUESTA (RAG, tools, notas de memoria, small talk),
así que también protege de lo que pudiera colarse por cualquier fuente:

| Comprobación | Tipo de fallo | Qué hace |
|---|---|---|
| Respuesta vacía | estructural | la sustituye por un mensaje honesto |
| Marcadores de rol / plantilla de chat, etiquetas de delimitación, JSON crudo | estructural | los elimina |
| Longitud > 2.500 caracteres | estructural | recorta |
| Parte RAG sin línea «Fuente:» (`check_rag_answer`) | estructural | añade una «Fuente:» honesta |
| Canario o frases del system prompt | seguridad | bloquea la respuesta entera |
| Tarifas negociadas con carriers / términos comerciales | contenido | elimina la frase |
| Dirección, coordenadas o rutas internas de almacenes | contenido | elimina la frase |
| Referencias de pedido que no son de la sesión | contenido | elimina la frase |
| Emails o teléfonos | contenido | elimina la frase |
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from ..memory import policy as memory_policy
from . import events
from .authorization import normalize_reference, order_references
from .isolation import DELIMITER_TAGS
from .input_guard import ROLE_MARKERS
from .normalize import fold
from .prompts import CANARY, PROMPT_FINGERPRINTS

MAX_ANSWER_CHARS = 2500
EMPTY_ANSWER = ("No he podido generar una respuesta fiable. Puedo ayudarte con el seguimiento de un envío, "
                "una devolución o una incidencia si me das más detalles.")
LEAK_ANSWER = ("No puedo compartir esa información. Soy el agente de soporte de TrackFlow: puedo ayudarte con el "
               "seguimiento de envíos, devoluciones e incidencias.")
REDACTED_NOTE = "[He omitido parte de la respuesta porque contenía información que no puedo compartir.]"
MISSING_SOURCE = "Fuente: ninguna citada por el modelo (verifícalo con el equipo de CX)"

CARRIERS = r"(?:ups|fedex|dhl|mrw|seur)"
SENSITIVE_OUTPUT: dict[str, re.Pattern[str]] = {
    "negotiated_rates": re.compile(
        rf"\b(?:tarifas?|precios?|costes?|costos?|descuentos?)\s+(?:\w+\s+){{0,2}}(?:negociad\w*|pactad\w*|acordad\w*|confidencial\w*)"
        rf"(?:\s+\w+){{0,3}}\s+(?:con|de)\s+{CARRIERS}\b"
        rf"|\b{CARRIERS}\b[^.\n]{{0,40}}\d+(?:[.,]\d+)?\s*(?:€|eur|usd|\$|dolares|euros)"
        rf"|\b(?:trackflow\s+)?(?:paga|pagamos|abona)\s+(?:a\s+)?{CARRIERS}\b"
    ),
    "commercial_terms": re.compile(
        r"\b(?:contrato|acuerdo comercial|terminos comerciales|condiciones comerciales)\s+(?:de|con)\s+(?:la marca|el cliente)\s+\w+"
    ),
    "warehouse_location": re.compile(
        r"\b(?:pasillos?|estanterias?|racks?|muelles? de carga|codigos? de acceso|camaras? de seguridad|rutas? internas?|plano del almacen)\b"
        r"|-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}"
    ),
}


class OutputVerdict(BaseModel):
    answer: str
    issues: list[str] = []
    blocked: bool = False


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+|\n", text) if part.strip()]


# Fechas y horas (2026-11-20 11:05, 20/11/2026) no son teléfonos: se quitan antes de buscar datos de contacto.
DATE_TIME = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[ t]\d{2}:\d{2}(?::\d{2})?)?\b|\b\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2})?\b")


def _sentence_issues(sentence: str, authorized_refs: set[str]) -> list[str]:
    folded = DATE_TIME.sub(" ", fold(sentence))
    issues = [code for code, pattern in SENSITIVE_OUTPUT.items() if pattern.search(folded)]
    for code in ("customer_location", "personal_data"):
        if any(p.search(folded) for p in memory_policy.FORBIDDEN_PATTERNS[code][:3 if code == "customer_location" else 2]):
            issues.append("warehouse_location" if code == "customer_location" else "personal_data")
    foreign = [ref for ref in order_references(sentence) if ref not in authorized_refs]
    if foreign:
        issues.append("foreign_order")
    return sorted(set(issues))


def check_output(answer: str | None, *, authorized_refs: list[str] | None = None) -> OutputVerdict:
    """Valida y, si hace falta, repara o bloquea la respuesta final."""
    text = (answer or "").strip()
    issues: list[str] = []

    if not text:
        events.record(guard="output", category="empty_answer", failure_type="structural", action="repaired")
        return OutputVerdict(answer=EMPTY_ANSWER, issues=["empty_answer"])

    if CANARY.lower() in text.lower() or any(fingerprint in text for fingerprint in PROMPT_FINGERPRINTS):
        events.record(guard="output", category="prompt_leak", failure_type="security", action="blocked",
                      rules=["prompt_fingerprint"])
        return OutputVerdict(answer=LEAK_ANSWER, issues=["prompt_leak"], blocked=True)

    cleaned = ROLE_MARKERS.sub("", DELIMITER_TAGS.sub("", text))
    if re.match(r"^\s*[\[{]", cleaned) and re.search(r"[\]}]\s*$", cleaned):
        issues.append("raw_json")
    if cleaned != text:
        issues.append("template_markers")
    if issues:
        events.record(guard="output", category="format", failure_type="structural", action="repaired", rules=issues)
    text = cleaned.strip() or EMPTY_ANSWER

    refs = {normalize_reference(ref) for ref in authorized_refs or []}
    kept, removed = [], []
    for sentence in _sentences(text):
        found = _sentence_issues(sentence, refs)
        if found:
            removed.extend(found)
        else:
            kept.append(sentence)
    if removed:
        events.record(guard="output", category="sensitive_data", failure_type="content", action="redacted",
                      rules=sorted(set(removed)))
        issues.extend(sorted(set(removed)))
        text = "\n".join(kept + [REDACTED_NOTE]) if kept else LEAK_ANSWER

    if len(text) > MAX_ANSWER_CHARS:
        events.record(guard="output", category="too_long", failure_type="structural", action="repaired")
        issues.append("too_long")
        text = text[:MAX_ANSWER_CHARS].rsplit(" ", 1)[0] + "…"
    return OutputVerdict(answer=text, issues=issues)


def check_rag_answer(answer: str) -> str:
    """La parte RAG debe terminar con su «Fuente:» (contrato del prompt). Si falta, se añade una honesta."""
    if re.search(r"(?im)^\s*fuente\s*:", answer):
        return answer
    events.record(guard="output", category="missing_source", failure_type="structural", action="repaired")
    return f"{answer.rstrip()}\n{MISSING_SOURCE}"
