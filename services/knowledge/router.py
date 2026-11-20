"""`POST /knowledge/query`: asistente comercial de TrackFlow sobre la base de conocimiento.

El router no contiene lógica de recuperación ni de generación: importa y llama
a `query()` de `data/pipelines/rag.py`. Al cliente solo le llega `answer`; los
chunks y las puntuaciones se quedan en el log del servidor.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.api.security import get_current_user
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.api"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `api`.
    from api.security import get_current_user

from data.pipelines import rag as rag_pipeline

from .schemas import KnowledgeQueryRequest, KnowledgeQueryResponse

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = logging.getLogger("api.knowledge")

ASSISTANT_UNAVAILABLE = "El asistente comercial no está disponible en este momento."


@router.post("/query", response_model=KnowledgeQueryResponse)
def knowledge_query(
    body: KnowledgeQueryRequest,
    _: Annotated[dict, Depends(get_current_user)],
) -> KnowledgeQueryResponse:
    """Responde con la voz de un vendedor de TrackFlow usando solo la base de conocimiento."""
    try:
        answer = rag_pipeline.query(body.question)
    except Exception:
        logger.exception("Fallo del pipeline RAG")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ASSISTANT_UNAVAILABLE)
    return KnowledgeQueryResponse(answer=answer)
