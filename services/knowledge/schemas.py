"""Contratos de `POST /knowledge/query` (Hito 7 — RAG y Base de Conocimiento).

La respuesta solo contiene `answer`, el texto generado por el modelo: nunca
chunks, puntuaciones de similitud ni IDs de Qdrant.
"""

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=3, max_length=500, description="Pregunta en lenguaje natural.")


class KnowledgeQueryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
