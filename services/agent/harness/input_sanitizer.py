"""Saneado explícito de la entrada del usuario antes de que llegue al modelo (proyecto NIST · Protect).

Las guardias (`input_guard.py`) **deciden** sobre una copia normalizada del texto,
pero hasta ahora la pregunta llegaba al prompt y al trace tal como la escribió el
usuario: con caracteres invisibles, de control o de ancho completo. Este módulo
**limpia** el texto que se usará de verdad (prompt, búsqueda semántica, trace):

1. **Unicode NFKC**: el ancho completo («ｉｇｎｏｒａ») y las ligaduras pasan a su forma
   normal, la misma que ven las guardias.
2. **Fuera los caracteres invisibles y de control** (categorías Cf y Cc, salvo
   salto de línea y tabulador): zero-width, BOM, marcas de dirección (RLO), que
   sirven para esconder órdenes al lector humano.
3. **Espacios**: los tabuladores pasan a espacio, se colapsan las rachas de
   espacios y se permiten como mucho dos saltos de línea seguidos.
4. **Repeticiones**: un mismo carácter repetido más de `MAX_REPEAT` veces se
   recorta (inundación de tokens: «aaaa…», «!!!!…»).
5. **Longitud**: como mucho `MAX_INPUT_CHARS` caracteres (el mismo límite que
   validan los esquemas de la API y del chat: aquí cubre también la CLI y los scripts).

No reescribe palabras ni quita las órdenes: eso lo deciden las guardias, que
necesitan ver el intento para bloquearlo y registrarlo. Cada cambio queda como
evento `input_sanitized` (tipo de fallo `structural`) en el trace de la corrida.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from . import events

MAX_INPUT_CHARS = 500
MAX_REPEAT = 12
_REPEATS = re.compile(r"(.)\1{%d,}" % MAX_REPEAT, re.S)
_SPACES = re.compile(r"[ \t\f\v ]+")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class SanitizedInput:
    text: str
    changes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


def _drop_invisible(text: str) -> str:
    return "".join(
        c for c in text
        if c in "\n\t" or unicodedata.category(c) not in {"Cf", "Cc", "Co", "Cs"}
    )


def sanitize_user_input(text: str | None, *, record: bool = True) -> SanitizedInput:
    """Devuelve el texto limpio y la lista de cambios aplicados (vacía si ya estaba limpio)."""
    original = text or ""
    changes: list[str] = []

    value = unicodedata.normalize("NFKC", original)
    if value != original:
        changes.append("unicode_nfkc")

    stripped = _drop_invisible(value)
    if stripped != value:
        changes.append("invisible_or_control_chars")
    value = stripped.replace("\r\n", "\n").replace("\r", "\n")

    spaced = "\n".join(_SPACES.sub(" ", line).strip() for line in value.split("\n"))
    spaced = _BLANK_LINES.sub("\n\n", spaced).strip()
    if spaced != value.strip():
        changes.append("whitespace")
    value = spaced

    trimmed = _REPEATS.sub(lambda m: m.group(1) * MAX_REPEAT, value)
    if trimmed != value:
        changes.append("repeated_chars")
    value = trimmed

    if len(value) > MAX_INPUT_CHARS:
        value = value[:MAX_INPUT_CHARS].rstrip()
        changes.append("truncated")

    result = SanitizedInput(text=value, changes=tuple(changes))
    if record:
        record_event(result, original)
    return result


def record_event(result: SanitizedInput, original: str | None) -> None:
    """Evento `input_sanitized` si hubo un cambio relevante (los espacios no cuentan)."""
    relevant = [change for change in result.changes if change != "whitespace"]
    if relevant:
        events.record(
            guard="input_sanitizer", category="input_sanitized", failure_type="structural", action="sanitized",
            rules=relevant, detail=f"{len(original or '')} → {len(result.text)} caracteres",
        )
