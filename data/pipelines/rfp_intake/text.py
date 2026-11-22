"""Utilidades de texto deterministas que comparten los agentes del flujo RFP.

- `fold()`: minúsculas sin tildes ni espacios repetidos, para comparar.
- `blocks()` / `clauses()`: trozos del Markdown con los que se reparten extractos.
- `numbers_in()` + `unanchored_numbers()`: la guarda «no inventes cifras»: un
  número que un agente escribe tiene que aparecer en el texto que recibió.
- `parse_json_object()`: el primer objeto JSON de la salida de un LLM.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

_SPACES = re.compile(r"\s+")


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SPACES.sub(" ", without_marks).strip().lower()


def contains(haystack: str, needle: str) -> bool:
    """`needle` aparece en `haystack` ignorando mayúsculas, tildes y espacios."""
    folded = fold(needle)
    return bool(folded) and folded in fold(haystack)


_NON_ALNUM = re.compile(r"[^0-9a-zñ]+")


def _tokens(text: str) -> list[str]:
    return [token for token in _NON_ALNUM.sub(" ", fold(text)).split() if token]


def loosely_contains(haystack: str, needle: str, *, min_coverage: float = 0.85) -> bool:
    """Cita «casi literal»: igual salvo puntuación, comillas o puntos suspensivos.

    Los LLM suelen recortar o puntuar distinto una cita; lo que importa es que
    las palabras salgan del documento: vale la cita completa normalizada o, si
    tiene ≥ 3 palabras, que el 85 % de ellas aparezcan en el texto.
    """
    needle_tokens = _tokens(needle)
    if not needle_tokens:
        return False
    hay_tokens = _tokens(haystack)
    normalized_needle = " ".join(needle_tokens)
    if normalized_needle in " ".join(hay_tokens):
        return True
    if len(needle_tokens) < 3:
        return False
    hay_set = set(hay_tokens)
    present = sum(token in hay_set for token in needle_tokens)
    return present / len(needle_tokens) >= min_coverage


# --------------------------------------------------------------------------- #
# Bloques y cláusulas
# --------------------------------------------------------------------------- #
_BULLET = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+")
_HEADING = re.compile(r"^\s*#+\s*")


def blocks(markdown: str) -> list[str]:
    """Párrafos y viñetas del Markdown, sin marcas, en orden y sin vacíos."""
    result: list[str] = []
    current: list[str] = []
    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                result.append(" ".join(current))
                current = []
            continue
        if _HEADING.match(line):
            if current:
                result.append(" ".join(current))
                current = []
            result.append(_HEADING.sub("", line).strip())
            continue
        if _BULLET.match(line):
            # Una viñeta abre bloque propio; sus líneas de continuación se le suman.
            if current:
                result.append(" ".join(current))
            current = [_BULLET.sub("", line).strip()]
            continue
        current.append(line)
    if current:
        result.append(" ".join(current))
    return [block for block in (_SPACES.sub(" ", b).strip() for b in result) if block]


_CLAUSE_SPLIT = re.compile(r"(?<=[.;!?])\s+|\s+[—–]\s+|;\s*")


def clauses(block: str) -> list[str]:
    """Frases y cláusulas de un bloque (corta en `.`, `;`, `—`)."""
    parts = [part.strip(" .;—–") for part in _CLAUSE_SPLIT.split(block or "")]
    return [part for part in parts if part]


# --------------------------------------------------------------------------- #
# Números anclados
# --------------------------------------------------------------------------- #
_NUMBER = re.compile(r"(?<![\w])(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)(\s?[kK]\b)?")


def _canonical(raw: str, thousands_suffix: str | None = None) -> str:
    value = raw
    # 15.000 / 15,000 → 15000 ; 2,5 / 2.5 → 2.5
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", value):
        value = re.sub(r"[.,]", "", value)
    else:
        value = value.replace(",", ".")
    if thousands_suffix:
        try:
            number = float(value) * 1000
        except ValueError:
            return value
        value = str(int(number)) if number.is_integer() else str(number)
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    return value


def numbers_in(text: str) -> set[str]:
    """Números de un texto en forma canónica (`5,000`, `5.000` y `5k` → `5000`)."""
    found: set[str] = set()
    for match in _NUMBER.finditer(text or ""):
        found.add(_canonical(match.group(1), match.group(2)))
        if match.group(2):
            found.add(_canonical(match.group(1)))
    return found


def unanchored_numbers(text: str, *sources: str) -> set[str]:
    """Números de `text` que no aparecen en ninguna de las `sources`."""
    allowed: set[str] = set()
    for source in sources:
        allowed |= numbers_in(source)
    return {number for number in numbers_in(text) if number not in allowed}


# --------------------------------------------------------------------------- #
# Salida JSON de un LLM
# --------------------------------------------------------------------------- #
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(raw: str) -> dict[str, Any]:
    """Primer objeto JSON de la respuesta (tolera ```json y texto alrededor)."""
    text = _FENCE.sub("", (raw or "").strip())
    start = text.find("{")
    if start < 0:
        raise ValueError("la respuesta no contiene un objeto JSON")
    decoder = json.JSONDecoder()
    value, _ = decoder.raw_decode(text[start:])
    if not isinstance(value, dict):
        raise ValueError("la respuesta JSON no es un objeto")
    return value


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True
