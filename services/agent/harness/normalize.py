"""Normalización de texto para las guardias deterministas.

Un intento de inyección rara vez llega "limpio": con tildes o sin ellas,
mayúsculas, caracteres invisibles, l33t ("1gn0r4"), letras separadas
("i g n o r a") o caracteres de ancho completo. Las guardias comparan contra
tres variantes del mismo texto:

* `folded` — NFKC, sin caracteres de formato (zero-width…), minúsculas, sin tildes
  y con los espacios colapsados.
* `deleet` — `folded` con los sustitutos habituales de letras (0→o, 1→i, 3→e, 4→a,
  5→s, 7→t, @→a, $→s).
* `compact` — solo letras de `deleet`, sin espacios ni signos: detecta frases
  partidas ("i.g.n.o.r.a t-u-s i n s t r u c c i o n e s").
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def strip_format_chars(text: str) -> str:
    """Quita caracteres invisibles (categoría Cf: zero-width, BOM, marcas de dirección) y de control."""
    return "".join(
        c for c in text if unicodedata.category(c) != "Cf" and (c in "\n\t" or unicodedata.category(c) != "Cc")
    )


def fold(text: str | None) -> str:
    value = unicodedata.normalize("NFKC", strip_format_chars(text or ""))
    value = "".join(c for c in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", value).strip()


@dataclass(frozen=True)
class Variants:
    original: str
    folded: str
    deleet: str
    compact: str

    def any(self, pattern: re.Pattern[str]) -> bool:
        return bool(pattern.search(self.folded) or pattern.search(self.deleet))


def variants(text: str | None) -> Variants:
    folded = fold(text)
    deleet = folded.translate(LEET)
    compact = re.sub(r"[^a-z]", "", deleet)
    return Variants(original=text or "", folded=folded, deleet=deleet, compact=compact)
