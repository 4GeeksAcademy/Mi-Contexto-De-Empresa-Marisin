"""Métricas de legibilidad del Markdown para anticipar el costo de procesamiento.

No son una nota literaria: sirven para estimar cuánto va a costar que los
agentes lean la RFP (tokens) y lo densa que es (frases largas, palabras
polisílabas → más extractos, más preguntas abiertas, más iteraciones en la
Parte 2).

- Las puntuaciones clásicas (Flesch-Kincaid, Gunning Fog, Flesch Reading Ease)
  salen de `py-readability-metrics` cuando está instalado, el texto tiene las
  100 palabras que exige la librería y NLTK tiene `punkt`. Si no, se calculan
  aquí con las mismas fórmulas; `source` dice cuál se usó.
- Esas fórmulas están pensadas para inglés. Para RFPs en español se añade la
  fórmula de Fernández Huerta (adaptación de Flesch al castellano).
- `estimated_tokens` ≈ caracteres / 4 y `estimated_llm_input_tokens` multiplica
  por el número de agentes que leen texto de la RFP en este grafo.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

from .text import fold

logger = logging.getLogger("rfp_intake.metrics")

_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:['’-][A-Za-zÀ-ÖØ-öø-ÿ]+)*|\d+(?:[.,]\d+)*")
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)|\n\s*\n")
_VOWEL_GROUPS = re.compile(r"[aeiouyáéíóúü]+")

_SPANISH_HINTS = {
    "de", "la", "el", "los", "las", "para", "con", "una", "por", "nuestro", "nuestra",
    "propuesta", "solicitud", "almacenamiento", "devoluciones", "envios", "pedidos", "que",
}
_ENGLISH_HINTS = {
    "the", "and", "for", "with", "our", "we", "you", "proposal", "request", "shipping",
    "orders", "warehousing", "returns", "please", "would", "could",
}


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def _sentences(text: str) -> int:
    pieces = [piece for piece in _SENTENCE_END.split(text) if piece.strip()]
    return max(1, len(pieces))


def syllables(word: str) -> int:
    folded = fold(word)
    if not folded.isalpha():
        return 1
    groups = _VOWEL_GROUPS.findall(folded)
    count = len(groups)
    if folded.endswith("e") and count > 1 and not folded.endswith(("le", "ee")):
        count -= 1  # "e" muda final en inglés
    return max(1, count)


def detect_language(text: str) -> str:
    tokens = [fold(token) for token in _words(text)]
    spanish = sum(token in _SPANISH_HINTS for token in tokens)
    english = sum(token in _ENGLISH_HINTS for token in tokens)
    if spanish == english == 0:
        return "unknown"
    return "es" if spanish >= english else "en"


def _internal_scores(word_count: int, sentence_count: int, syllable_count: int, complex_words: int) -> dict[str, float]:
    words_per_sentence = word_count / sentence_count
    syllables_per_word = syllable_count / word_count
    return {
        "flesch_kincaid_grade": round(0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59, 2),
        "flesch_reading_ease": round(206.835 - 1.015 * words_per_sentence - 84.6 * syllables_per_word, 2),
        "gunning_fog": round(0.4 * (words_per_sentence + 100 * complex_words / word_count), 2),
    }


def _library_scores(text: str) -> dict[str, float] | None:
    try:
        from readability import Readability  # py-readability-metrics

        readability = Readability(text)
        return {
            "flesch_kincaid_grade": round(float(readability.flesch_kincaid().score), 2),
            "flesch_reading_ease": round(float(readability.flesch().score), 2),
            "gunning_fog": round(float(readability.gunning_fog().score), 2),
        }
    except Exception as exc:  # < 100 palabras, NLTK sin `punkt`, librería ausente…
        logger.info("py-readability-metrics no aplicable (%s: %s); fórmulas internas", type(exc).__name__, exc)
        return None


def cost_tier(estimated_tokens: int, grade: float) -> str:
    """Bajo / medio / alto: tamaño del documento, corregido por su densidad."""
    if estimated_tokens > 6000 or (estimated_tokens > 3000 and grade >= 14):
        return "alto"
    if estimated_tokens > 1500 or grade >= 14:
        return "medio"
    return "bajo"


def readability_metrics(markdown: str, *, llm_readers: int = 1) -> dict[str, Any]:
    """Métricas del Markdown convertido. `llm_readers` = agentes que lo leen."""
    words = _words(markdown)
    word_count = len(words)
    estimated_tokens = math.ceil(len(markdown) / 4)
    base: dict[str, Any] = {
        "language": detect_language(markdown),
        "characters": len(markdown),
        "word_count": word_count,
        "estimated_tokens": estimated_tokens,
        "estimated_llm_input_tokens": estimated_tokens * max(1, llm_readers),
    }
    if word_count == 0:
        return {**base, "sentence_count": 0, "source": "empty", "cost_tier": "bajo"}

    sentence_count = _sentences(markdown)
    syllable_counts = [syllables(word) for word in words]
    syllable_count = sum(syllable_counts)
    complex_words = sum(count >= 3 for count in syllable_counts)
    scores = _library_scores(markdown)
    source = "py-readability-metrics" if scores else "internal"
    if scores is None:
        scores = _internal_scores(word_count, sentence_count, syllable_count, complex_words)

    syllables_per_100 = 100 * syllable_count / word_count
    sentences_per_100 = 100 * sentence_count / word_count
    result = {
        **base,
        "sentence_count": sentence_count,
        "avg_words_per_sentence": round(word_count / sentence_count, 2),
        "avg_syllables_per_word": round(syllable_count / word_count, 2),
        **scores,
        "fernandez_huerta": round(206.84 - 0.60 * syllables_per_100 - 1.02 * sentences_per_100, 2),
        "source": source,
    }
    result["cost_tier"] = cost_tier(estimated_tokens, float(result["flesch_kincaid_grade"]))
    return result
