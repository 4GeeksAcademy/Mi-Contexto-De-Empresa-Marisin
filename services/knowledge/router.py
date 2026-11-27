"""`POST /knowledge/query`: asistente comercial de TrackFlow sobre la base de conocimiento.

El router no contiene lógica de recuperación ni de generación: importa y llama
a `query()` de `data/pipelines/rag.py`. Al cliente solo le llega `answer`; los
chunks y las puntuaciones se quedan en el log del servidor.

NIST · Protect: la pregunta se sanea (`sanitize_user_input`) antes de llegar al
modelo y la ruta gasta el mismo presupuesto de llamadas al LLM que el agente
(`usage_limits`): 429 con `Retry-After` al agotarlo.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.api.security import get_current_user, require_staff
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.api"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `api`.
    from api.security import get_current_user, require_staff

from data.pipelines import rag as rag_pipeline

try:
    from services.agent.harness import usage_limits
    from services.agent.harness.input_sanitizer import sanitize_user_input
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.agent"}:
        raise
    from agent.harness import usage_limits
    from agent.harness.input_sanitizer import sanitize_user_input

from .schemas import KnowledgeQueryRequest, KnowledgeQueryResponse

# Solo personal de TrackFlow (D8): un cliente (`user`) recibe 403 en todo el router.
router = APIRouter(prefix="/knowledge", tags=["knowledge"], dependencies=[Depends(require_staff)])
logger = logging.getLogger("api.knowledge")

ASSISTANT_UNAVAILABLE = "El asistente comercial no está disponible en este momento."


@router.post("/query", response_model=KnowledgeQueryResponse)
def knowledge_query(
    body: KnowledgeQueryRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> KnowledgeQueryResponse:
    """Responde con la voz de un vendedor de TrackFlow usando solo la base de conocimiento."""
    verdict = usage_limits.consume(user, endpoint="POST /knowledge/query")
    if not verdict.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=usage_limits.RATE_LIMITED_DETAIL,
            headers={"Retry-After": str(verdict.retry_after or 60)},
        )
    question = sanitize_user_input(body.question).text
    if not question:
        raise HTTPException(status_code=422, detail="La pregunta está vacía después de limpiarla.")
    try:
        answer = rag_pipeline.query(question)
    except Exception:
        logger.exception("Fallo del pipeline RAG")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ASSISTANT_UNAVAILABLE)
    return KnowledgeQueryResponse(answer=answer)
