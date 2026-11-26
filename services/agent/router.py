"""Endpoints del agente de soporte (LangGraph).

* `POST /agent/query` — invoca el grafo compilado mediante `run_agent()` y
  devuelve `{run_id, status, answer, sources}`. No contiene lógica de recuperación ni de
  generación. Convive con `POST /knowledge/query` (Hito 7), que no cambia.
* `GET /agent/traces/{run_id}` — el trace guardado de una corrida (solo
  `admin` o `manager`: incluye los chunks recuperados).
* `GET /agent/memory` — memoria consolidada del agente (solo `admin`/`manager`).
* `GET /agent/memory/audit` — registro de propuestas y decisiones (solo `admin`/`manager`).
* `GET /agent/guardrails/summary` — cuántas veces se activó cada guardrail, por tipo de
  fallo (solo `admin`/`manager`; `?since=` para acotar a una sesión de pruebas).

Errores: pregunta vacía → 422 con el mensaje del nodo `invalid_question`;
fallo de cualquier nodo → 503 con un mensaje claro y la referencia `run_id`,
nunca con el stack trace.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

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
from .harness import events as guard_events
from .memory import store as memory_store
from .memory.backend import MemoryUnavailable
from .schemas import (
    AgentMemoryAuditResponse,
    AgentMemoryInfo,
    AgentMemoryResponse,
    AgentQueryRequest,
    AgentQueryResponse,
    AgentTraceResponse,
    GuardrailInfo,
    GuardrailSummaryResponse,
    MemoryDecisionView,
    MemoryProposalView,
)
from .tracing import load_trace

router = APIRouter(prefix="/agent", tags=["agent"])
logger = logging.getLogger("api.agent")

TRACE_ROLES = {"admin", "manager"}
AGENT_UNAVAILABLE = "El agente de soporte no ha podido completar la consulta. Inténtalo de nuevo en unos minutos."


MEMORY_UNAVAILABLE = "La memoria del agente no está disponible ahora mismo."


def memory_info(memory: dict) -> AgentMemoryInfo:
    proposal = memory.get("proposal") or {}
    decision = memory.get("decision")
    return AgentMemoryInfo(
        pending_proposal=MemoryProposalView.model_validate(proposal) if proposal.get("status") == "proposed" else None,
        decision=MemoryDecisionView.model_validate(decision) if decision else None,
        notes_used=len(memory.get("notes") or []),
    )


def require_trace_role(user: dict) -> None:
    if user.get("role") not in TRACE_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo admin o manager pueden ver esto.")


@router.post("/query", response_model=AgentQueryResponse)
def agent_query(
    body: AgentQueryRequest,
    user: Annotated[dict, Depends(get_current_user)],
) -> AgentQueryResponse:
    """Responde a la pregunta recorriendo el grafo del agente."""
    conversation_id = str(body.conversation_id) if body.conversation_id else None
    try:
        result = runner.run_agent(body.question, conversation_id=conversation_id, user=user)
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
        run_id=result.run_id,
        conversation_id=result.conversation_id or "",
        status=result.status,
        answer=result.answer,
        sources=list(result.sources),
        memory=memory_info(result.memory),
        guardrail=GuardrailInfo.model_validate(result.guardrail) if result.guardrail else None,
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


@router.get("/memory", response_model=AgentMemoryResponse)
def agent_memory(user: Annotated[dict, Depends(get_current_user)]) -> AgentMemoryResponse:
    """Memoria consolidada: slots (categoría + ámbito) con sus hechos aprobados y vigentes."""
    require_trace_role(user)
    try:
        slots = memory_store.get_store().list_slots()
    except MemoryUnavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=MEMORY_UNAVAILABLE)
    return AgentMemoryResponse(total_slots=len(slots), total_facts=sum(len(s.facts) for s in slots), slots=slots)


@router.get("/memory/audit", response_model=AgentMemoryAuditResponse)
def agent_memory_audit(
    user: Annotated[dict, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> AgentMemoryAuditResponse:
    """Últimas entradas del registro de auditoría (propuestas, decisiones, caducidades, bloqueos)."""
    require_trace_role(user)
    try:
        events = memory_store.get_store().audit_log(limit)
    except MemoryUnavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=MEMORY_UNAVAILABLE)
    return AgentMemoryAuditResponse(events=events)


@router.get("/guardrails/summary", response_model=GuardrailSummaryResponse)
def agent_guardrails_summary(
    user: Annotated[dict, Depends(get_current_user)],
    since: Annotated[str | None, Query(max_length=40, description="ISO 8601: solo eventos desde ese instante.")] = None,
) -> GuardrailSummaryResponse:
    """Cuántas veces se activó cada guardrail (por guardia, categoría, tipo de fallo y acción)."""
    require_trace_role(user)
    try:
        summary = guard_events.get_log().summary(since=since)
    except MemoryUnavailable:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="El registro de guardrails no está disponible.")
    return GuardrailSummaryResponse.model_validate(summary)


# Chat del First-line CX agent por WebSocket (Sistemas en tiempo real · Parte 2): `/agent/chat/...`.
from .chat.router import router as chat_router  # noqa: E402

router.include_router(chat_router)
