"""RAG de TrackFlow · Fase 2: recuperación y generación.

* `retrieve()` — embebe la pregunta con el mismo `embed()` de la indexación,
  busca en `trackflow_knowledge` y **filtra por `min_score`** (puede devolver
  menos de k resultados, o ninguno). Devuelve payloads, nunca objetos del SDK.
* `generate_answer()` — arma el prompt con la voz del BRIEFING (vendedor de
  TrackFlow para los account managers de Miguel Torres) y llama al modelo de
  **generación** (`LLM_MODEL`).
* `query()` — la única función para consumidores externos:
  `retrieve()` + `generate_answer()`. Un agente posterior puede llamar a las
  dos por separado sin repetir la recuperación.

La respuesta siempre la redacta el modelo: el texto crudo de los chunks nunca
se devuelve tal cual. Si no hay contexto por encima del umbral, el modelo
recibe la instrucción explícita de decir que no hay información suficiente.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from data.process.rag import (
    COLLECTION_NAME,
    check_models,
    embed,
    get_qdrant_client,
    load_settings,
)

DEFAULT_K = 5
# Umbral de similitud coseno, calibrado con `python scripts/rag_eval.py` y el
# modelo pplx-embed-v1-0.6b: chunk correcto ≥ 0,539 en las 16 preguntas de la
# base y ≤ 0,383 en las preguntas fuera de alcance. 0,46 queda en el punto medio
# (justificación en docs/rag/rag-design.md §4).
DEFAULT_MIN_SCORE = 0.46
TEMPERATURE = 0.0  # respuestas reproducibles y pegadas al contexto

DOCUMENT_LABELS = {
    "sla-delivery": "SLA de Entrega",
    "returns-policy": "Política de Devoluciones",
    "carrier-coverage": "Cobertura de Transportistas",
    "storage-pricing": "Tarifas de Almacenamiento",
}

NO_CONTEXT_MARKER = "SIN CONTEXTO RELEVANTE"

SYSTEM_PROMPT = """\
Eres el asistente comercial de TrackFlow, empresa de logística de última milla y \
almacenaje con operaciones en Los Ángeles (Estados Unidos) y Zaragoza (España).
Ayudas a los account managers y al equipo de desarrollo de negocio de Miguel Torres \
(Director Comercial). Redacta la respuesta como la diría un vendedor de TrackFlow en \
una llamada con una marca cliente o prospecto: tono profesional y cercano, en español, \
directo, de 2 a 6 frases, listo para decirlo en voz alta.

Reglas obligatorias:
1. Usa SOLO la información del CONTEXTO. No uses conocimiento general ni supongas \
condiciones que no aparezcan en él.
2. Copia exactamente cada cifra, porcentaje, tarifa, moneda y plazo del contexto. No \
redondees, no conviertas monedas y no combines cifras de documentos distintos.
3. Nunca prometas condiciones que no estén en los acuerdos estándar. Si piden algo \
fuera de lo documentado (descuentos, excepciones, plazos especiales), di que no es \
estándar y que requiere aprobación:
   - descuentos o tarifas preferenciales de almacenamiento: aprobación de Miguel Torres;
   - excepciones en la elección de transportista: aprobación de Carlos Vega;
   - devoluciones internacionales: gestión manual del equipo de Sofía Ramos.
4. Nunca prometas el SLA de entrega en fechas de alta demanda declaradas (Black \
Friday, Navidad, Rebajas de enero): explica lo que dice el contexto sobre esas fechas \
y recomienda avisar al cliente con antelación.
5. Nunca describas las devoluciones internacionales como automáticas.
6. Nunca menciones un descuento de almacenamiento sin decir que requiere la \
aprobación de Miguel Torres.
7. Si el CONTEXTO dice "{no_context}" o no contiene la respuesta, dilo con claridad: \
que la base de conocimiento no tiene información suficiente para responder con \
seguridad, sin dar cifras, y sugiere consultarlo con el responsable del área.
8. Termina con una línea "Fuente:" que liste el documento y la sección de cada \
fragmento que hayas usado, tal como aparecen en el contexto. Si no usaste ninguno, \
escribe "Fuente: ninguna (sin información en la base de conocimiento)".
""".format(no_context=NO_CONTEXT_MARKER)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Recuperación
# --------------------------------------------------------------------------- #
def retrieve(query: str, *, k: int = DEFAULT_K, min_score: float = DEFAULT_MIN_SCORE) -> list[dict[str, Any]]:
    """Los k chunks más cercanos a `query` con similitud ≥ `min_score`.

    Devuelve solo los payloads supervivientes (dicts con `source_document`,
    `section`, `text`…), en orden de similitud. Puede devolver menos de k o
    una lista vacía: forzar contexto irrelevante es peor que no tener ninguno.
    """
    if not query or not query.strip():
        return []
    if k < 1:
        raise ValueError("k debe ser ≥ 1")
    response = get_qdrant_client().query_points(
        collection_name=COLLECTION_NAME,
        query=embed(query),
        limit=k,
        with_payload=True,
    )
    results = []
    for point in response.points:
        payload = dict(point.payload or {})
        logger.debug(
            "retrieve score=%.4f %s · %s", point.score, payload.get("source_document"), payload.get("section")
        )
        if point.score >= min_score:
            results.append(payload)
    logger.info("retrieve: %d/%d chunks superan min_score=%.2f", len(results), len(response.points), min_score)
    return results


# --------------------------------------------------------------------------- #
# Generación
# --------------------------------------------------------------------------- #
def format_context(context: list[dict[str, Any]]) -> str:
    """Contexto numerado con su origen para que la respuesta sea trazable."""
    if not context:
        return NO_CONTEXT_MARKER
    blocks = []
    for number, chunk in enumerate(context, 1):
        document = DOCUMENT_LABELS.get(chunk.get("source_document", ""), chunk.get("source_document", "?"))
        blocks.append(
            f"[{number}] Documento: {document} ({chunk.get('source_document')}) · "
            f"Sección: {chunk.get('section')}\n{chunk.get('text', '').strip()}"
        )
    return "\n\n".join(blocks)


def build_messages(question: str, context: list[dict[str, Any]]) -> list[dict[str, str]]:
    user = (
        "CONTEXTO (fragmentos recuperados de la base de conocimiento de TrackFlow):\n"
        "---\n"
        f"{format_context(context)}\n"
        "---\n\n"
        f"PREGUNTA DEL ACCOUNT MANAGER: {question.strip()}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def get_generation_client():
    """Cliente OpenAI-compatible para `/chat/completions` del acceso LLM de 4Geeks."""
    from openai import OpenAI

    settings = load_settings()
    if not settings.llm_api_url or not settings.llm_api_key:
        raise RuntimeError("Faltan LLM_API_URL / LLM_API_KEY en .env.")
    return OpenAI(base_url=settings.llm_api_url, api_key=settings.llm_api_key)


def generate_answer(question: str, context: list[dict[str, Any]]) -> str:
    """Prompt + llamada al modelo de GENERACIÓN (`LLM_MODEL`). Devuelve solo el texto."""
    settings = load_settings()
    check_models(settings)
    completion = get_generation_client().chat.completions.create(
        model=settings.llm_model,
        messages=build_messages(question, context),
        temperature=TEMPERATURE,
    )
    answer = (completion.choices[0].message.content or "").strip()
    if not answer:
        raise RuntimeError("El modelo de generación devolvió una respuesta vacía")
    return answer


# --------------------------------------------------------------------------- #
# Fidelidad (KPI del BRIEFING §4): cifras de la respuesta presentes en el contexto
# --------------------------------------------------------------------------- #
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def unsupported_figures(answer: str, context: list[dict[str, Any]], question: str = "") -> list[str]:
    """Cifras de la respuesta que no aparecen en ningún chunk recuperado.

    Los números que da la propia pregunta (p. ej. "una marca con 60 m³") no
    cuentan como inventados: el modelo puede repetirlos al razonar sobre ellos.
    """
    sources = [chunk.get("text", "") for chunk in context] + [question]
    available = {n.replace(",", ".") for text in sources for n in NUMBER.findall(text)}
    answer_without_refs = re.sub(r"\[\d+\]", "", answer)  # referencias [1], [2]… al contexto
    return sorted({n for n in NUMBER.findall(answer_without_refs) if n.replace(",", ".") not in available})


# --------------------------------------------------------------------------- #
# Punto de entrada único
# --------------------------------------------------------------------------- #
def query(question: str) -> str:
    """Respuesta generada por el modelo a partir del contexto recuperado.

    Es la única función que deben usar el endpoint y la UI. Las puntuaciones y
    los chunks solo se registran en el log del servidor.
    """
    context = retrieve(question)
    answer = generate_answer(question, context)
    unsupported = unsupported_figures(answer, context, question)
    if unsupported:
        logger.warning("Respuesta con cifras que no están en el contexto: %s", unsupported)
    return answer
