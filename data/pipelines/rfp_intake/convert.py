"""PDF → Markdown con MarkItDown, antes de que ningún agente lea la RFP.

Las RFPs llegan siempre en PDF y pesan mucho en tokens. El grafo convierte el
PDF guardado en `data/raw/rfp/` una sola vez; a partir de ahí todos los agentes
(y la Parte 2, a través del ticket) trabajan con el Markdown limpio.

`clean_markdown()` quita el ruido típico de la extracción con pdfminer: viñetas
que llegan como `(cid:127)`, caracteres de control, espacios al final de línea y
más de una línea en blanco seguida.
"""

from __future__ import annotations

import re
from pathlib import Path

PDF_MAGIC = b"%PDF-"

_CID_BULLET = re.compile(r"^[ \t]*\(cid:\d+\)[ \t]*", re.MULTILINE)
_CID_ANY = re.compile(r"\(cid:\d+\)")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TRAILING = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANKS = re.compile(r"\n{3,}")


class ConversionError(RuntimeError):
    """El PDF no se pudo convertir o no tiene texto extraíble."""


def looks_like_pdf(content: bytes) -> bool:
    return content[:1024].lstrip().startswith(PDF_MAGIC)


def clean_markdown(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _CID_BULLET.sub("- ", text)
    text = _CID_ANY.sub("", text)
    text = _CONTROL.sub("", text)
    text = _TRAILING.sub("", text)
    text = _BLANKS.sub("\n\n", text)
    return text.strip() + "\n" if text.strip() else ""


def pdf_to_markdown(pdf_path: Path | str) -> str:
    """Convierte el PDF con MarkItDown y devuelve el Markdown limpio."""
    from markitdown import MarkItDown

    path = Path(pdf_path)
    if not path.is_file():
        raise ConversionError(f"No existe el PDF {path}")
    try:
        result = MarkItDown(enable_plugins=False).convert(str(path))
    except Exception as exc:  # MarkItDown envuelve los errores de pdfminer
        raise ConversionError(f"MarkItDown no pudo convertir el PDF: {type(exc).__name__}: {exc}") from exc
    markdown = clean_markdown(result.text_content or "")
    if not markdown.strip():
        # PDF escaneado sin capa de texto: sin OCR no hay nada que leer.
        raise ConversionError("El PDF no contiene texto extraíble (¿es un escaneo sin OCR?)")
    return markdown
