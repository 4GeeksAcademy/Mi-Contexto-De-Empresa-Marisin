"""Endpoints del agente de soporte (LangGraph).

* `POST /agent/query` — invoca el grafo compilado mediante `run_agent()` y
  devuelve `{run_id, status, answer, sources}`. No contiene lógica de recuperación ni de
  generación. Convive con `POST /knowledge/query` (Hito 7), que no cambia.
* `GET /agent/traces/{run_id}` — el trace guardado de una corrida (solo
  `admin` o `manager`: incluye los chunks recuperados).

Errores: pregunta vacía → 422 con el mensaje del nodo `invalid_question`;
fallo de cualquier nodo → 503 con un mensaje claro y la referencia `run_id`,
nunca con el stack trace.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.api.security import get_current_user
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.api"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `api`.
    from api.security import get_current_user

from . import runner
from .graph import AGENT_GRAPH  # noqa: F401  — compila el grafo al arrancar la API
from .schemas import AgentQueryRequest, AgentQueryResponse, AgentTraceResponse
from .tracing import load_trace

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger("api.agent")

TRACE_ROLES = {"admin", "manager"}
AGENT_UNAVAILABLE = "El agente de soporte no ha podido completar la consulta. Inténtalo de nuevo en unos minutos."


@router.post("/query", response_model=AgentQueryResponse)
def agent_query(
    body: AgentQueryRequest,
    _: Annotated[dict, Depends(get_current_user)],
) -> AgentQueryResponse:
    """Responde a la pregunta recorriendo el grafo del agente."""
    try:
        result = runner.run_agent(body.question)
    except runner.AgentRunError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{AGENT_UNAVAILABLE} Referencia: {exc.run_id}",
        )
    except Exception:
        logger.exception("Fallo del agente fuera de los nodos")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=AGENT_UNAVAILABLE)
    if result.status == "invalid":
        raise HTTPException(status_code=422, detail=result.answer)
    return AgentQueryResponse(
        run_id=result.run_id, status=result.status, answer=result.answer, sources=list(result.sources)
    )


@router.get("/traces/{run_id}", response_model=AgentTraceResponse)
def agent_trace(
    run_id: UUID,
    user: Annotated[dict, Depends(get_current_user)],
) -> AgentTraceResponse:
    """Trace de una corrida: nodos ejecutados, orden, salidas y checkpoints."""
    if user.get("role") not in TRACE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo admin o manager pueden ver los traces.")
    trace = load_trace(str(run_id))
    if trace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe un trace con ese run_id.")
    return AgentTraceResponse.model_validate(trace)
