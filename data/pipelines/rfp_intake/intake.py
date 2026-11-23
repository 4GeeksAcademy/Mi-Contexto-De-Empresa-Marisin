"""Recepción de una RFP: valida el PDF, lo guarda en `data/raw/rfp/` y crea el ticket.

Es la parte síncrona del `POST`: no convierte ni llama a ningún agente, para que
la API responda en milisegundos con `202`. El nombre del fichero en disco es el
`rfp_id` (UUID), nunca el nombre que manda el usuario: así no hay rutas
manipuladas ni colisiones; el nombre original se guarda en el ticket.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import config
from .convert import looks_like_pdf
from .store import RfpStore


class UploadRejected(ValueError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


_SAFE_NAME = re.compile(r"[^\w.\- ()áéíóúñÁÉÍÓÚÑ]+")


def safe_display_name(filename: str | None) -> str:
    name = Path(filename or "rfp.pdf").name.strip() or "rfp.pdf"
    return _SAFE_NAME.sub("_", name)[:200]


def validate_pdf(content: bytes, filename: str | None) -> None:
    if not content:
        raise UploadRejected(422, "El fichero está vacío.")
    if len(content) > config.MAX_PDF_BYTES:
        raise UploadRejected(413, f"El PDF supera el máximo de {config.MAX_PDF_BYTES // (1024 * 1024)} MB.")
    if not looks_like_pdf(content):
        raise UploadRejected(415, "Las RFPs se reciben siempre en PDF: el fichero no es un PDF válido.")
    if filename and not filename.lower().endswith(".pdf"):
        raise UploadRejected(415, "Las RFPs se reciben siempre en PDF (extensión .pdf).")


def accept_upload(
    content: bytes,
    filename: str | None,
    store: RfpStore,
    *,
    uploaded_by: str | None,
    raw_dir: Path | None = None,
) -> dict[str, Any]:
    """Guarda el PDF y crea el ticket en `analizando`. Lanza `UploadRejected` si no vale."""
    validate_pdf(content, filename)
    target_dir = Path(raw_dir or config.RAW_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    rfp_id = str(uuid4())
    pdf_path = target_dir / f"{rfp_id}.pdf"
    tmp_path = pdf_path.with_suffix(".pdf.tmp")
    tmp_path.write_bytes(content)
    os.replace(tmp_path, pdf_path)
    try:
        return store.create_ticket(
            rfp_id=rfp_id,
            raw_pdf_path=_display_path(pdf_path),
            original_filename=safe_display_name(filename),
            file_sha256=hashlib.sha256(content).hexdigest(),
            file_size_bytes=len(content),
            uploaded_by=uploaded_by,
        )
    except Exception:
        pdf_path.unlink(missing_ok=True)  # sin ticket no hay PDF huérfano
        raise


def _display_path(path: Path) -> str:
    """Ruta relativa a la raíz del repo si cae dentro (`data/raw/rfp/<id>.pdf`)."""
    try:
        return str(path.resolve().relative_to(config.ROOT))
    except ValueError:
        return str(path.resolve())


def resolve_pdf_path(raw_pdf_path: str) -> Path:
    path = Path(raw_pdf_path)
    return path if path.is_absolute() else config.ROOT / path
