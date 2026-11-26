"""Agentes evaluadores de cada sección y juez que arma el `EvaluationResult`.

Tres evaluadores independientes que el grafo ejecuta **en paralelo** sobre cada
borrador. Cada uno recibe solo lo que necesita (pregunta de diseño 1):

- **Legibilidad** (`evaluate_readability`): solo el texto. Mide la prosa
  (sin tablas ni citas literales del cliente) con `py-readability-metrics`
  cuando aplica y con Fernández Huerta para el español (`metrics.py`, Parte 1).
- **Pertinencia** (`evaluate_relevance`): el texto + los aspectos clave y las
  preguntas abiertas de su departamento en el handoff + el nombre del cliente.
  Comprueba que la sección responde a lo que pidió la RFP.
- **Cumplimiento** (`evaluate_compliance`): el texto + la moneda del país +
  las fuentes permitidas (handoff, tarifario, políticas). Verifica las reglas
  concretas del BRIEFING §5 y la de «nunca inventes» de §2.3, con un `rule_id`
  por regla; no es una opinión de estilo.

Son deterministas a propósito: el mismo borrador da siempre el mismo
resultado (sin bucles por un juez caprichoso) y cada fallo trae la frase o
cifra que lo causa. El LLM está en el generador; aquí solo se mide.
`judge()` une los tres resultados y redacta `feedback_for_generator`: una
instrucción concreta por fallo.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .. import metrics
from ..text import fold, numbers_in, unanchored_numbers
from . import config
from .schemas import (
    ComplianceCheck,
    EvaluationResult,
    ReadabilityCheck,
    RelevanceCheck,
    Violation,
)

# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
_QUOTE = re.compile(r"«[^»]*»|\"[^\"]*\"")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_EMPHASIS = re.compile(r"[*_`]+")


def prose_text(markdown: str) -> str:
    """Prosa de la sección: sin tablas, títulos, marcas ni citas literales del cliente."""
    sentences: list[str] = []
    for raw in (markdown or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("|") or line.startswith("#"):
            continue
        line = _BULLET.sub("", line)
        line = _QUOTE.sub("lo indicado", line)
        line = _EMPHASIS.sub("", line).strip()
        if not line:
            continue
        if line[-1] not in ".!?":
            line += "."
        sentences.append(line)
    return "\n".join(sentences)


_WORDS = re.compile(r"[a-z0-9ñ]+")
_STOPWORDS = {
    "para", "por", "con", "del", "los", "las", "una", "uno", "que", "como", "cual", "cuales", "cuanto", "cuantos",
    "cuantas", "este", "esta", "esto", "sobre", "segun", "the", "and", "for", "with", "what", "how", "many", "much",
    "cliente", "rfp", "requisito", "trackflow", "hay", "espera", "indica", "necesita",
}


def stems(text: str) -> set[str]:
    """Raíces burdas (6 letras) de las palabras de contenido."""
    return {w[:6] for w in _WORDS.findall(fold(text)) if len(w) >= 3 and w not in _STOPWORDS}


def _coverage(needle: str, haystack_stems: set[str]) -> float:
    wanted = stems(needle)
    if not wanted:
        return 1.0
    return len(wanted & haystack_stems) / len(wanted)


def _clauses(markdown: str) -> list[str]:
    parts: list[str] = []
    for line in (markdown or "").splitlines():
        line = _BULLET.sub("", line.strip())
        parts += [piece.strip() for piece in re.split(r"(?<=[.!?;])\s+", line) if piece.strip()]
    return parts


# --------------------------------------------------------------------------- #
# Legibilidad
# --------------------------------------------------------------------------- #
def evaluate_readability(content: str) -> ReadabilityCheck:
    prose = prose_text(content)
    total_words = len(_WORDS.findall(fold(content)))
    result = metrics.readability_metrics(prose) if prose else {"word_count": 0, "language": "unknown"}
    language = result.get("language", "unknown")
    avg_words = float(result.get("avg_words_per_sentence") or 0)
    problems: list[str] = []
    if language == "en":
        score = result.get("flesch_kincaid_grade")
        metric = "flesch_kincaid_grade"
        if score is None or score > config.MAX_FLESCH_KINCAID_GRADE:
            problems.append(f"Flesch-Kincaid {score} (máximo {config.MAX_FLESCH_KINCAID_GRADE})")
    else:
        score = result.get("fernandez_huerta")
        metric = "fernandez_huerta"
        if score is None or score < config.MIN_FERNANDEZ_HUERTA:
            problems.append(f"Fernández Huerta {score} (mínimo {config.MIN_FERNANDEZ_HUERTA:.0f})")
    if avg_words > config.MAX_AVG_WORDS_PER_SENTENCE:
        problems.append(f"{avg_words} palabras por frase de media (máximo {config.MAX_AVG_WORDS_PER_SENTENCE:.0f})")
    if total_words < config.MIN_SECTION_WORDS:
        problems.append(f"sección de {total_words} palabras (mínimo {config.MIN_SECTION_WORDS})")
    if total_words > config.MAX_SECTION_WORDS:
        problems.append(f"sección de {total_words} palabras (máximo {config.MAX_SECTION_WORDS})")
    return ReadabilityCheck(
        passed=not problems,
        score=score,
        details={
            "metric": metric,
            "language": language,
            "section_words": total_words,
            "prose_words": result.get("word_count", 0),
            "avg_words_per_sentence": avg_words,
            "fernandez_huerta": result.get("fernandez_huerta"),
            "flesch_kincaid_grade": result.get("flesch_kincaid_grade"),
            "flesch_reading_ease": result.get("flesch_reading_ease"),
            "gunning_fog": result.get("gunning_fog"),
            "source": result.get("source"),
            "problems": problems,
        },
    )


# --------------------------------------------------------------------------- #
# Pertinencia
# --------------------------------------------------------------------------- #
DEPARTMENT_SCOPE = {
    "warehouse": ("almacenamiento", ("almacen",)),
    "lastmile": ("envíos de última milla", ("envio", "entrega")),
    "reverse": ("devoluciones", ("devoluc",)),
}
GENERIC_TOPICS = {"requis", "rfp"}
MIN_TOPIC_COVERAGE = 0.5
MIN_DETAIL_COVERAGE = 0.4
MIN_QUESTION_COVERAGE = 0.6


def evaluate_relevance(
    content: str,
    *,
    department_id: str,
    client_name: str | None,
    key_aspects: list[dict[str, str]],
    open_questions: list[str],
) -> RelevanceCheck:
    found = stems(content)
    folded = fold(content)
    missing: list[str] = []
    covered: list[str] = []
    for aspect in key_aspects:
        topic = aspect.get("topic", "")
        topic_stems = stems(topic) - GENERIC_TOPICS
        # Nombrar el aspecto tal cual (lo que pide el prompt del generador) siempre cuenta, también
        # para temas genéricos como «Requisito de la RFP», que no tienen raíces propias.
        named = bool(fold(topic).strip()) and fold(topic).strip() in folded
        topic_ok = named or (
            bool(topic_stems) and len(topic_stems & found) / len(topic_stems) >= MIN_TOPIC_COVERAGE
        )
        detail_ok = _coverage(aspect.get("detail", ""), found) >= MIN_DETAIL_COVERAGE
        if topic_ok or detail_ok:
            covered.append(topic)
        else:
            missing.append(f"aspecto clave «{topic}»")
    for question in open_questions:
        if _coverage(question, found) < MIN_QUESTION_COVERAGE:
            missing.append(f"pregunta abierta «{question}»")
    if client_name:
        first = next((w for w in _WORDS.findall(fold(client_name)) if len(w) >= 3), "")
        if first and first not in folded:
            missing.append(f"nombre del cliente «{client_name}»")
    label, needles = DEPARTMENT_SCOPE[department_id]
    if not any(needle in folded for needle in needles):
        missing.append(f"alcance del departamento ({label})")
    if "precio" not in folded:
        missing.append("apartado «Precios» de la propuesta económica")
    return RelevanceCheck(
        passed=not missing,
        missing_aspects=missing,
        details={"aspects_total": len(key_aspects), "aspects_covered": covered, "open_questions": len(open_questions)},
    )


# --------------------------------------------------------------------------- #
# Cumplimiento (BRIEFING §5 + §2.3)
# --------------------------------------------------------------------------- #
_CURRENCY_PATTERNS = {
    "USD": re.compile(r"\busd\b|us\$|\$|\bdolar(?:es)?\b|\bdollars?\b"),
    "EUR": re.compile(r"\beur\b|€|\beuros?\b"),
}
_PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s?%")
_SLA_WORDS = ("sla", "a tiempo", "on-time", "on time")
_RETURNS_WORDS = ("devoluc", "devuelt", "return", "reverse", "reacondicion", "inspeccion", "restock")
_DURATION = re.compile(
    r"(\d+(?:[.,]\d+)?)(?:\s*(?:-|–|a|to|y|o)\s*(\d+(?:[.,]\d+)?))?\s*"
    r"(h\b|hrs?\b|horas?\b|hours?\b|dias?\b|days?\b)"
)
_UNDER = re.compile(r"(?:menos de|en menos de|under|less than|within|antes de)\s*(\d+(?:[.,]\d+)?)\s*(h\b|hrs?\b|horas?\b|hours?\b)")
_SAME_DAY = ("mismo dia", "same day", "same-day", "dia siguiente", "next day", "next-day", "en el dia")
_NEGATION = ("nunca", "jamas", "no se compromete", "no promete", "never", "not ")
_CARRIER = re.compile(r"\b(" + "|".join(config.CARRIERS) + r")\b")
_RATE_WORDS = ("tarifa", "rate", "precio", "price", "coste", "costo", "cost", "descuento", "discount")
_NEGOTIATED = ("negociad", "negotiated")
_CARRIER_WORDS = ("transportist", "carrier")
SMALL_COUNT = 10  # «3 preguntas», «2 kg»…: conteos pequeños no se tratan como cifras de negocio


def _currencies(text: str) -> set[str]:
    folded = fold(text)
    return {code for code, pattern in _CURRENCY_PATTERNS.items() if pattern.search(folded)}


def currencies_in(text: str) -> set[str]:
    """Monedas que cita un texto (USD/EUR); también lo usa el detector de conflictos de la Parte 3."""
    return _currencies(text)


def _hours(value: str, unit: str) -> float:
    number = float(value.replace(",", "."))
    return number * 24 if unit.startswith(("dia", "day")) else number


def _markdown_tables(content: str) -> list[list[str]]:
    tables: list[list[str]] = []
    current: list[str] = []
    for line in (content or "").splitlines() + [""]:
        if line.strip().startswith("|"):
            current.append(line.strip())
        elif current:
            tables.append(current)
            current = []
    return tables


def check_currency(content: str, expected: str | None) -> list[Violation]:
    found = _currencies(content)
    if expected is None:
        return [Violation(rule_id=config.RULE_CURRENCY, detail="Sin país confirmado no hay moneda: no se puede cotizar.")]
    violations = []
    others = sorted(found - {expected})
    if others:
        evidence = next((c for c in _clauses(content) if _currencies(c) - {expected}), "")
        violations.append(
            Violation(
                rule_id=config.RULE_CURRENCY,
                detail=f"Cotiza en {', '.join(others)}; el cliente se cotiza en {expected}.",
                evidence=evidence[:300],
            )
        )
    if expected not in found:
        violations.append(Violation(rule_id=config.RULE_CURRENCY, detail=f"No aparece ningún precio en {expected}."))
    return violations


def check_sla(content: str) -> list[Violation]:
    for line in (content or "").splitlines():
        folded = fold(line)
        if any(word in folded for word in _SLA_WORDS) and _PERCENT.search(folded):
            return []
    return [Violation(rule_id=config.RULE_SLA, detail="No indica el SLA de entrega a tiempo en %.")]


def check_returns_turnaround(content: str) -> list[Violation]:
    violations = []
    for clause in _clauses(content):
        folded = fold(clause)
        if not any(word in folded for word in _RETURNS_WORDS):
            continue
        negated = any(word in folded for word in _NEGATION)
        too_fast = []
        for match in _DURATION.finditer(folded):
            unit = match.group(3)
            for value in (match.group(1), match.group(2)):
                if value and _hours(value, unit) < config.MIN_RETURNS_HOURS:
                    too_fast.append(f"{value} {unit}")
        under = [m for m in _UNDER.finditer(folded) if _hours(m.group(1), m.group(2)) <= config.MIN_RETURNS_HOURS]
        same_day = [phrase for phrase in _SAME_DAY if phrase in folded]
        if (too_fast or under or same_day) and not negated:
            violations.append(
                Violation(
                    rule_id=config.RULE_RETURNS_48H,
                    detail="Promete procesar devoluciones en menos de 48 horas.",
                    evidence=clause[:300],
                )
            )
    return violations


def check_discount_table(content: str) -> list[Violation]:
    for table in _markdown_tables(content):
        header = fold(table[0])
        rows = [row for row in table[1:] if not re.fullmatch(r"[|\s:-]+", row)]
        if ("descuento" in header or "discount" in header) and sum("%" in row for row in rows) >= 2:
            return []
    return [Violation(rule_id=config.RULE_DISCOUNT_TABLE, detail="Falta la tabla de descuentos por volumen.")]


def check_carrier_rates(content: str) -> list[Violation]:
    violations = []
    for line in (content or "").splitlines():
        folded = fold(line)
        carrier = _CARRIER.search(folded)
        negotiated = any(w in folded for w in _NEGOTIATED) and (
            carrier or any(w in folded for w in _CARRIER_WORDS)
        )
        priced = carrier and (_currencies(line) and numbers_in(line) or any(w in folded for w in _RATE_WORDS))
        if negotiated or priced:
            violations.append(
                Violation(
                    rule_id=config.RULE_CARRIER_RATES,
                    detail="Revela tarifas o precios de un transportista concreto.",
                    evidence=line.strip()[:300],
                )
            )
    return violations


def check_invented_figures(content: str, sources: list[str]) -> list[Violation]:
    invented = sorted(
        n for n in unanchored_numbers(content, *sources)
        if not (n.isdigit() and int(n) <= SMALL_COUNT)
    )
    if not invented:
        return []
    return [
        Violation(
            rule_id=config.RULE_NO_INVENTED_FIGURES,
            detail="Cifras que no están en la RFP, el tarifario ni las políticas: " + ", ".join(invented),
            evidence=", ".join(invented),
        )
    ]


def evaluate_compliance(content: str, *, currency: str | None, sources: list[str]) -> ComplianceCheck:
    violations = (
        check_currency(content, currency)
        + check_sla(content)
        + check_returns_turnaround(content)
        + check_discount_table(content)
        + check_carrier_rates(content)
        + check_invented_figures(content, sources)
    )
    return ComplianceCheck(passed=not violations, rule_ids=list(config.COMPLIANCE_RULES), violations=violations)


# --------------------------------------------------------------------------- #
# Juez: EvaluationResult + feedback para el generador
# --------------------------------------------------------------------------- #
def _compliance_advice(violation: Violation, currency: str | None) -> str:
    rule = violation.rule_id
    if rule == config.RULE_CURRENCY:
        if currency is None:
            return f"[{rule}] Falta el país del cliente: no cotices y pide confirmarlo (EE. UU. → USD, España → EUR)."
        return f"[{rule}] {violation.detail} Escribe todos los precios en {currency}, como en el tarifario."
    if rule == config.RULE_SLA:
        return (f"[{rule}] Añade en «Condiciones de servicio» el SLA de entrega a tiempo: «TrackFlow se compromete "
                "a un 90 % de entregas a tiempo al mes, medido por país».")
    if rule == config.RULE_RETURNS_48H:
        return (f"[{rule}] Quita la promesa «{violation.evidence}»: el procesamiento de devoluciones nunca baja de "
                "48 horas; usa el plazo del tarifario (72 horas).")
    if rule == config.RULE_DISCOUNT_TABLE:
        return (f"[{rule}] Añade en «Descuentos por volumen» la tabla del tarifario "
                "(| Pedidos al mes | Descuento por volumen |) y di qué tramo aplica.")
    if rule == config.RULE_CARRIER_RATES:
        return (f"[{rule}] Quita «{violation.evidence}»: no se dan tarifas ni precios por transportista, solo el "
                "precio final por envío al cliente.")
    if rule == config.RULE_NO_INVENTED_FIGURES:
        return (f"[{rule}] Quita o corrige estas cifras, que no salen de la RFP, el tarifario ni las políticas: "
                f"{violation.evidence}.")
    return f"[{rule}] {violation.detail}"


def build_feedback(
    readability: ReadabilityCheck, relevance: RelevanceCheck, compliance: ComplianceCheck, currency: str | None
) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for violation in compliance.violations:
        advice = _compliance_advice(violation, currency)
        if advice not in seen:
            seen.add(advice)
            lines.append(advice)
    if not relevance.passed:
        lines.append(
            "[relevance] Responde también a: " + "; ".join(relevance.missing_aspects)
            + ". Nombra cada aspecto clave en «Qué pide el cliente» y cada pregunta en «Datos pendientes del cliente»."
        )
    if not readability.passed:
        problems = "; ".join(readability.details.get("problems") or [])
        lines.append(
            f"[readability] {problems}. Divide las frases largas (menos de 25 palabras) y usa palabras más corrientes."
        )
    if not lines:
        return "Sin cambios: la sección cumple legibilidad, pertinencia y lineamientos."
    return "\n".join(f"- {line}" for line in lines)


def section_id(ticket_id: int | None, department_id: str) -> str:
    return f"{ticket_id if ticket_id is not None else 'local'}:{department_id}"


def judge(
    *,
    ticket_id: int | None,
    department_id: str,
    iteration: int,
    currency: str | None,
    readability: ReadabilityCheck,
    relevance: RelevanceCheck,
    compliance: ComplianceCheck,
) -> EvaluationResult:
    overall = readability.passed and relevance.passed and compliance.passed
    return EvaluationResult(
        section_id=section_id(ticket_id, department_id),
        department_id=department_id,
        iteration=iteration,
        readability=readability,
        relevance=relevance,
        compliance=compliance,
        overall_pass=overall,
        feedback_for_generator=build_feedback(readability, relevance, compliance, currency),
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )


def evaluation_dict(result: EvaluationResult) -> dict:
    """Forma persistida/devuelta: `pass` en lugar de `passed` (forma del enunciado)."""
    return result.model_dump(mode="json", by_alias=True)
