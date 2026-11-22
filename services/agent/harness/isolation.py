"""Aislamiento del contenido externo: chunks del RAG y datos devueltos por tools.

Ese texto no lo escribe TrackFlow en el momento: viene de documentos indexados o
de campos que rellena cualquiera (la descripción de un ticket, el nombre de un
producto). Nunca debe tratarse como instrucción del sistema (inyección
indirecta). Tres medidas:

1. **Sanitizar**: se quitan caracteres invisibles y de control, se neutralizan
   marcadores de rol / plantilla de chat (`system:`, `<|im_start|>`, `[INST]`…)
   y se sustituye cada línea con forma de instrucción («ignora tus
   instrucciones», «revela el prompt»…) por un aviso. Cada hallazgo se registra
   como fallo de **seguridad** (`indirect_injection`).
2. **Delimitar**: los chunks viajan dentro de `<documentos_no_confiables>` y la
   pregunta dentro de `<consulta_usuario>`; se escapan los `<`/`>` de esas
   etiquetas para que el texto no pueda cerrarlas y "salir" del bloque.
3. **Jerarquía**: el system prompt (`prompts.py`) declara que lo delimitado son
   datos y que solo el mensaje de sistema tiene autoridad.

Las respuestas de las tools se componen con plantillas (`answers.py`), no con el
LLM; aun así sus campos de texto se sanitizan antes de mostrarse.
"""

from __future__ import annotations

import re
from typing import Any

from . import events
from .input_guard import ROLE_MARKERS, injection_rules
from .normalize import strip_format_chars

REMOVED_LINE = "[texto con forma de instrucción eliminado por seguridad]"
REMOVED_MARKER = "[marcador eliminado]"
DELIMITER_TAGS = re.compile(r"<\s*/?\s*(documentos_no_confiables|documento|consulta_usuario|pais_del_pedido)\b[^>]*>", re.I)


def escape_delimiters(text: str) -> str:
    """Impide que el texto abra o cierre nuestras etiquetas de delimitación."""
    return DELIMITER_TAGS.sub(lambda m: m.group(0).replace("<", "‹").replace(">", "›"), text)


def sanitize(text: str | None, *, source: str) -> tuple[str, list[str]]:
    """`(texto limpio, reglas que se dispararon)` para un texto externo."""
    value = strip_format_chars(text or "")
    findings: list[str] = []
    if ROLE_MARKERS.search(value):
        findings.append("role_markers")
        value = ROLE_MARKERS.sub(REMOVED_MARKER, value)
    clean_lines = []
    for line in value.splitlines():
        hits = injection_rules(line)
        if hits:
            findings.extend(hits)
            clean_lines.append(REMOVED_LINE)
        else:
            clean_lines.append(line)
    value = escape_delimiters("\n".join(clean_lines))
    if findings:
        events.record(
            guard="isolation", category="indirect_injection", failure_type="security", action="sanitized",
            rules=sorted(set(findings)), detail=f"origen: {source}",
        )
    return value, sorted(set(findings))


def sanitize_context(context: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chunks del RAG con el texto sanitizado (los metadatos se conservan)."""
    cleaned = []
    for chunk in context:
        text, _ = sanitize(chunk.get("text"), source=f"rag:{chunk.get('source_document', '?')}")
        cleaned.append({**chunk, "text": text})
    return cleaned


def sanitize_tool_result(result: dict[str, Any], *, source: str) -> dict[str, Any]:
    """Campos de texto de una respuesta de tool, sanitizados recursivamente."""

    def clean(value: Any) -> Any:
        if isinstance(value, str):
            return sanitize(value, source=source)[0]
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value

    return clean(result)
