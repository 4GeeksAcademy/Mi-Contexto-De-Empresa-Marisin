"""RAG de TrackFlow · Fase 1: preparación de datos e indexación.

BRIEFING: Hito 7 — RAG y Base de Conocimiento (TrackFlow). El equipo comercial
de Miguel Torres (account managers y business development) necesita un
asistente que responda como un vendedor de TrackFlow a partir de los cuatro
documentos fuente copiados en `docs/company-knowledge-base/`.

Responsabilidades de este módulo (una por función):

* `load_documents()` — lee los `.md` de la base de conocimiento.
* `chunk_document()` — divide cada documento en chunks semánticos.
* `embed()` — convierte un texto en vector con el **modelo de embeddings**
  (`EMBEDDING_MODEL`), distinto del modelo de generación (`LLM_MODEL`).
* `setup()` — crea/recrea la colección `trackflow_knowledge` en Qdrant e
  inserta los chunks con IDs deterministas (idempotente).

Uso::

    python -m data.process.rag          # indexa y muestra el conteo de chunks
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_DIR = ROOT / "docs" / "company-knowledge-base"

# Valores exactos del BRIEFING (§2 y §3).
COMPANY = "trackflow"
COLLECTION_NAME = "trackflow_knowledge"
SOURCE_DOCUMENTS = {
    "trackflow-sla-delivery.es.md": "sla-delivery",
    "trackflow-returns-policy.es.md": "returns-policy",
    "trackflow-carrier-coverage.es.md": "carrier-coverage",
    "trackflow-storage-pricing.es.md": "storage-pricing",
}
MIN_CHUNKS_PER_DOCUMENT = 3  # BRIEFING §5
# Espacio de nombres fijo para los IDs deterministas de los puntos (uuid5).
POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://trackflow.example/rag/trackflow_knowledge")
# Una etiqueta "Etiqueta: …" al inicio de un bloque se usa como subsección.
SUBSECTION_LABEL = re.compile(r"^([^:\n]{3,45}):\s")
LIST_ITEM = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Configuración (siempre desde el entorno / .env; nunca claves en el código)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RagSettings:
    llm_api_url: str
    llm_api_key: str
    llm_model: str
    embedding_api_url: str
    embedding_api_key: str
    embedding_model: str
    qdrant_url: str
    qdrant_api_key: str | None


def load_settings() -> RagSettings:
    """Lee la configuración del RAG. `EMBEDDING_API_*` heredan de `LLM_API_*`."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # pragma: no cover - python-dotenv es dependencia del proyecto
        pass
    llm_api_url = os.getenv("LLM_API_URL", "").strip()
    llm_api_key = os.getenv("LLM_API_KEY", "").strip()
    return RagSettings(
        llm_api_url=llm_api_url,
        llm_api_key=llm_api_key,
        llm_model=os.getenv("LLM_MODEL", "").strip(),
        embedding_api_url=os.getenv("EMBEDDING_API_URL", "").strip() or llm_api_url,
        embedding_api_key=os.getenv("EMBEDDING_API_KEY", "").strip() or llm_api_key,
        embedding_model=os.getenv("EMBEDDING_MODEL", "").strip(),
        qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333").strip(),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", "").strip() or None,
    )


def check_models(settings: RagSettings) -> None:
    """Dos modelos, dos trabajos: el de embeddings nunca puede ser el de generación."""
    if not settings.embedding_model:
        raise RuntimeError("Falta EMBEDDING_MODEL en .env (modelo de embeddings de 4Geeks).")
    if not settings.llm_model:
        raise RuntimeError("Falta LLM_MODEL en .env (modelo de generación de 4Geeks).")
    if settings.embedding_model == settings.llm_model:
        raise RuntimeError(
            "EMBEDDING_MODEL y LLM_MODEL deben ser modelos distintos: "
            "embed() usa un modelo de embeddings dedicado y query() uno de generación."
        )


def get_qdrant_client():
    """Cliente del SDK de Qdrant (`QDRANT_URL`; `QDRANT_API_KEY` solo en Qdrant Cloud)."""
    from qdrant_client import QdrantClient

    settings = load_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30)


def get_embedding_client():
    """Cliente OpenAI-compatible para el endpoint `/embeddings` del acceso LLM de 4Geeks."""
    from openai import OpenAI

    settings = load_settings()
    if not settings.embedding_api_url or not settings.embedding_api_key:
        raise RuntimeError("Faltan LLM_API_URL / LLM_API_KEY (o EMBEDDING_API_*) en .env.")
    return OpenAI(base_url=settings.embedding_api_url, api_key=settings.embedding_api_key)


# --------------------------------------------------------------------------- #
# Carga y chunking semántico
# --------------------------------------------------------------------------- #
def load_documents(kb_dir: Path = KNOWLEDGE_BASE_DIR) -> dict[str, str]:
    """Devuelve {nombre de fichero: contenido} de los cuatro documentos del BRIEFING."""
    documents = {}
    for filename in SOURCE_DOCUMENTS:
        path = kb_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f"Falta el documento fuente {path} (BRIEFING §2)")
        documents[filename] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return documents


def _language(filename: str) -> str:
    match = re.search(r"\.([a-z]{2})\.md$", filename)
    return match.group(1) if match else "es"


def _blocks(body: str) -> list[str]:
    """Bloques separados por línea en blanco (párrafos, listas o párrafo + lista)."""
    return [block.strip() for block in re.split(r"\n\s*\n", body) if block.strip()]


def _is_list(block: str) -> bool:
    return bool(LIST_ITEM.match(block.splitlines()[0]))


def _semantic_units(body: str) -> list[str]:
    """Une un párrafo introductorio que termina en ':' con el bloque que introduce.

    Así una regla nunca queda separada de su condición: "TrackFlow cobra
    almacenamiento según volumen…:" viaja junto a sus tarifas, y "El proceso
    estándar… funciona así:" junto a sus pasos numerados.
    """
    units: list[str] = []
    pending_intro: str | None = None
    for block in _blocks(body):
        if pending_intro is not None:
            units.append(f"{pending_intro}\n{block}")
            pending_intro = None
        elif block.rstrip().endswith(":") and not _is_list(block):
            pending_intro = block
        elif _is_list(block) and units and units[-1].rstrip().endswith(":"):
            units[-1] = f"{units[-1]}\n{block}"
        else:
            units.append(block)
    if pending_intro is not None:
        units.append(pending_intro)
    return units


def _unwrap(unit: str) -> str:
    """Deshace el ajuste de línea del Markdown: cada frase en una línea, cada
    elemento de lista en la suya (así "gestión\nmanual" vuelve a ser "gestión manual")."""
    lines: list[str] = []
    for raw in unit.splitlines():
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            continue
        continuation = raw[:1].isspace() and not LIST_ITEM.match(raw)  # sangría de un elemento de lista
        new_line = not lines or LIST_ITEM.match(raw) or (lines[-1].endswith(":") and not continuation)
        if new_line:
            lines.append(line)
        else:
            lines[-1] = f"{lines[-1]} {line}"
    return "\n".join(lines)


def _section(title: str, unit: str) -> str:
    """`Título › Etiqueta` si el bloque (o el que sigue a su intro) empieza con "Etiqueta: …"."""
    lines = unit.splitlines()
    for position, line in enumerate(lines):
        starts_block = position == 0 or lines[position - 1].rstrip().endswith(":")
        match = SUBSECTION_LABEL.match(line)
        if starts_block and match and not LIST_ITEM.match(line):
            return f"{title} › {match.group(1).strip()}"
    return title


def chunk_document(filename: str, markdown: str) -> list[dict[str, Any]]:
    """Divide un documento en chunks semánticos con el payload del BRIEFING (§3).

    Unidad = párrafo completo o lista completa (con su frase introductoria).
    Nunca se corta por número de caracteres. El `text` lleva delante la
    sección para que cada chunk se entienda solo (y se embebe tal cual).
    """
    source_document = SOURCE_DOCUMENTS[filename]
    lines = markdown.strip().splitlines()
    title = next((line[2:].strip() for line in lines if line.startswith("# ")), source_document)
    body = "\n".join(line for line in lines if not line.startswith("# "))

    chunks = []
    for index, unit in enumerate(_semantic_units(body)):
        section = _section(title, unit)
        body_text = _unwrap(unit)
        chunks.append(
            {
                "company": COMPANY,
                "source_document": source_document,
                "section": section,
                "language": _language(filename),
                "chunk_index": index,
                "text": f"{section}\n{body_text}",
            }
        )
    if len(chunks) < MIN_CHUNKS_PER_DOCUMENT:
        raise ValueError(f"{filename} produce {len(chunks)} chunks; el BRIEFING exige ≥ 3")
    return chunks


def build_chunks(kb_dir: Path = KNOWLEDGE_BASE_DIR) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for filename, markdown in load_documents(kb_dir).items():
        chunks.extend(chunk_document(filename, markdown))
    return chunks


def point_id(chunk: dict[str, Any]) -> str:
    """ID determinista: el mismo chunk siempre cae en el mismo punto (re-ejecutar = upsert)."""
    key = f"{chunk['company']}:{chunk['source_document']}:{chunk['chunk_index']}"
    return str(uuid.uuid5(POINT_NAMESPACE, key))


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #
def normalize_text(text: str) -> str:
    """Mismo preprocesado al indexar y al consultar: espacios colapsados, sin bordes."""
    return re.sub(r"\s+", " ", text).strip()


def embed(text: str) -> list[float]:
    """Vector de `text` con el modelo de EMBEDDINGS (`EMBEDDING_MODEL`).

    La misma función se usa para los chunks en `setup()` y para la pregunta en
    `retrieve()`. Nunca usa `LLM_MODEL` (generación): `check_models` lo impide.
    """
    clean = normalize_text(text)
    if not clean:
        raise ValueError("No se puede embeber un texto vacío")
    settings = load_settings()
    check_models(settings)
    response = get_embedding_client().embeddings.create(model=settings.embedding_model, input=clean)
    return list(response.data[0].embedding)


# --------------------------------------------------------------------------- #
# Indexación en Qdrant
# --------------------------------------------------------------------------- #
def _collection_vector_size(client, collection_name: str) -> int | None:
    if not client.collection_exists(collection_name):
        return None
    vectors = client.get_collection(collection_name).config.params.vectors
    return getattr(vectors, "size", None)


def setup(kb_dir: Path = KNOWLEDGE_BASE_DIR, client=None) -> dict[str, Any]:
    """Indexa la base de conocimiento en `trackflow_knowledge`. Idempotente.

    Estrategia: IDs deterministas (uuid5 de company + documento + chunk_index)
    y `upsert`, de modo que re-ejecutar sobrescribe los mismos puntos en lugar
    de duplicarlos. Si un documento pierde chunks, los puntos sobrantes se
    borran. La colección se (re)crea si no existe o si cambió la dimensión del
    modelo de embeddings.
    """
    from qdrant_client import models

    client = client or get_qdrant_client()
    chunks = build_chunks(kb_dir)
    vectors = [embed(chunk["text"]) for chunk in chunks]
    dimension = len(vectors[0])

    current_size = _collection_vector_size(client, COLLECTION_NAME)
    if current_size != dimension:
        if current_size is not None:
            logger.warning("Dimensión distinta (%s → %s): se recrea la colección", current_size, dimension)
            client.delete_collection(COLLECTION_NAME)
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )

    ids = [point_id(chunk) for chunk in chunks]
    client.upsert(
        collection_name=COLLECTION_NAME,
        points=[
            models.PointStruct(id=pid, vector=vector, payload=chunk)
            for pid, vector, chunk in zip(ids, vectors, chunks)
        ],
        wait=True,
    )

    existing: set[str] = set()
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=COLLECTION_NAME, limit=256, offset=offset, with_payload=False, with_vectors=False
        )
        existing.update(str(point.id) for point in points)
        if offset is None:
            break
    stale = sorted(existing - set(ids))
    if stale:
        client.delete(collection_name=COLLECTION_NAME, points_selector=models.PointIdsList(points=stale), wait=True)

    per_document: dict[str, int] = {}
    for chunk in chunks:
        per_document[chunk["source_document"]] = per_document.get(chunk["source_document"], 0) + 1
    return {
        "collection": COLLECTION_NAME,
        "chunks": len(chunks),
        "points_in_collection": client.count(collection_name=COLLECTION_NAME, exact=True).count,
        "vector_size": dimension,
        "distance": "cosine",
        "chunks_per_document": per_document,
        "stale_points_deleted": len(stale),
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    summary = setup()
    print(f"Colección: {summary['collection']}")
    print(f"Chunks indexados: {summary['chunks']} (puntos en Qdrant: {summary['points_in_collection']})")
    print(f"Dimensión del vector: {summary['vector_size']} · distancia: {summary['distance']}")
    for document, count in summary["chunks_per_document"].items():
        print(f"  {document:<17} {count} chunks")
    if summary["stale_points_deleted"]:
        print(f"Puntos obsoletos borrados: {summary['stale_points_deleted']}")


if __name__ == "__main__":
    main()
