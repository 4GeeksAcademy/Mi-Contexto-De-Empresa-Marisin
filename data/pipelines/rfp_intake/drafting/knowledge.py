"""Acceso del generador a la base de conocimiento de TrackFlow (mejora opcional del enunciado).

Es el mismo corpus que indexa el RAG del Hito 7 (`docs/company-knowledge-base/`,
colección Qdrant `trackflow_knowledge`). Dos modos (`RFP_DRAFT_KNOWLEDGE`):

- `files` (por defecto): cada departamento recibe los documentos de su política
  leídos del disco. Determinista, sin red y sin Qdrant: los tests y el modo
  `--offline` dan siempre lo mismo.
- `semantic`: busca con `data.pipelines.rag.retrieve()` (umbral `min_score`
  calibrado en el Hito 7). Si Qdrant o el modelo de embeddings fallan, vuelve a
  `files`: la base de conocimiento nunca bloquea la generación.

Lo que devuelve son datos para el prompt y fuentes de anclaje de cifras, nunca
instrucciones.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from ..config import ROOT
from . import config

logger = logging.getLogger("rfp_intake.drafting.knowledge")

KNOWLEDGE_DIR = ROOT / "docs" / "company-knowledge-base"
DOCUMENTS = {
    "sla-delivery": "trackflow-sla-delivery.es.md",
    "returns-policy": "trackflow-returns-policy.es.md",
    "carrier-coverage": "trackflow-carrier-coverage.es.md",
    "storage-pricing": "trackflow-storage-pricing.es.md",
}
# Políticas que necesita cada generador. Todos llevan el SLA (BRIEFING §5).
DEPARTMENT_DOCUMENTS = {
    "warehouse": ("storage-pricing", "sla-delivery"),
    "lastmile": ("sla-delivery", "carrier-coverage"),
    "reverse": ("returns-policy", "sla-delivery"),
}
SEMANTIC_QUERIES = {
    "warehouse": "tarifas de almacenamiento por metro cúbico y periodo de gracia",
    "lastmile": "SLA de entrega a tiempo y cobertura de transportistas por país",
    "reverse": "política de devoluciones, inspección y plazos",
}
MAX_SNIPPET_CHARS = 1800


@lru_cache(maxsize=None)
def _read(document_id: str) -> str:
    path: Path = KNOWLEDGE_DIR / DOCUMENTS[document_id]
    try:
        return path.read_text(encoding="utf-8").strip()[:MAX_SNIPPET_CHARS]
    except OSError:
        logger.warning("No se pudo leer %s de la base de conocimiento", path)
        return ""


def file_snippets(department_id: str) -> list[dict[str, str]]:
    snippets = []
    for document_id in DEPARTMENT_DOCUMENTS[department_id]:
        text = _read(document_id)
        if text:
            snippets.append({"document_id": document_id, "text": text})
    return snippets


def semantic_snippets(department_id: str) -> list[dict[str, str]]:
    from data.pipelines import rag

    results = rag.retrieve(SEMANTIC_QUERIES[department_id], k=3)
    snippets = []
    for item in results:
        text = str(item.get("text") or "").strip()
        if text:
            snippets.append({"document_id": str(item.get("source_document") or "rag"), "text": text})
    return snippets


def snippets_for(department_id: str, mode: str | None = None) -> list[dict[str, str]]:
    """Fragmentos de política para un departamento. Nunca lanza."""
    mode = (mode or config.KNOWLEDGE_MODE).lower()
    if mode == "semantic":
        try:
            found = semantic_snippets(department_id)
            if found:
                return found
            logger.info("Búsqueda semántica sin resultados para %s: documentos del disco", department_id)
        except Exception as exc:  # Qdrant parado, sin embeddings…
            logger.warning("Base de conocimiento semántica no disponible (%s): documentos del disco", type(exc).__name__)
    return file_snippets(department_id)
