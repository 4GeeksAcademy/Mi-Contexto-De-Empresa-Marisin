"""Recepción, borradores y aprobación de RFPs en modo ticket (Hito 9 · Partes 1-3) en el backend existente.

* `POST /rfp/tickets` — cuerpo = el PDF (`Content-Type: application/pdf`,
  `?filename=`). Guarda el PDF en `data/raw/rfp/`, crea el ticket en
  `analizando` y responde **202** al momento; el pipeline corre en segundo plano.
* `GET /rfp/tickets` — tickets recientes (la UI hace poll mientras alguno está
  en `analizando`).
* `GET /rfp/tickets/{ticket_id}` — estado, clasificación, metadatos, secciones
  por departamento (con borrador y `EvaluationResult` desde la Parte 2), handoff
  para la Parte 2 y `drafting_handoff` para la Parte 3.
* `POST /rfp/tickets/{ticket_id}/drafts` — (Parte 2) relanza la generación y
  evaluación de borradores de un ticket con análisis completo (o ya redactado,
  con error o parado). Responde **202**; 409 si no se puede (descartado, sin
  handoff o generándose ahora mismo).
* `POST /rfp/tickets/{ticket_id}/approvals` — (Parte 3) abre (o reinicia) la
  aprobación humana: una rama por departamento, cada una en pausa hasta su
  responsable. **202**; 409 si el ticket no tiene borradores listos.
* `POST /rfp/tickets/{ticket_id}/approvals/{department_id}` — (Parte 3) la
  decisión del responsable (`approve` | `reject` | `request_changes`). Se valida
  antes de reanudar la rama (422 si no es válida, 409 si esa rama no espera
  aprobación). Aprobar o rechazar reanuda la rama al momento; pedir cambios
  responde 202 y la reescritura sigue en segundo plano.
* `GET /rfp/tickets/{ticket_id}/trace` — qué agente hizo qué y en qué orden
  (Partes 1, 2 y 3), con input, output y timestamps.
* `GET /rfp/tickets/{ticket_id}/document` — el documento final (404 hasta `terminado`).

Tras la Parte 1, la Parte 2 se encadena sola en segundo plano si el ticket
queda en la cola (`ready_for_drafting`; desactivable con `RFP_AUTO_DRAFT=0`), y
tras la Parte 2 se abre sola la aprobación (`ready_for_approval`; `RFP_AUTO_APPROVAL=0`).
El router no contiene lógica de agentes ni el grafo: importa y dispara
`data/pipelines/rfp_intake/`. Errores: PDF no válido → 415/413/422; sin
`DATABASE_URL` → 503; ticket inexistente → 404.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

try:
    # API arrancada desde la raíz del repo: `uvicorn services.api.main:app`.
    from services.api.database import engine
    from services.api.security import get_current_user
except ModuleNotFoundError as exc:
    if exc.name not in {"services", "services.api"}:
        raise
    # Contenedor de Docker: /app es `services/`, así que el paquete es `api`.
    from api.database import engine
    from api.security import get_current_user

from data.pipelines.rfp_intake import config as rfp_config
from data.pipelines.rfp_intake import intake, runner
from data.pipelines.rfp_intake.approval import config as approval_config
from data.pipelines.rfp_intake.approval import runner as approval_runner
from data.pipelines.rfp_intake.approval.checkpoint import CheckpointerUnavailable
from data.pipelines.rfp_intake.drafting import runner as drafting_runner
from data.pipelines.rfp_intake.sql_store import SqlRfpStore
from data.pipelines.rfp_intake.store import NotApprovable, NotDraftable, RfpStore, TicketNotFound, is_stale

from .schemas import (
    RfpApprovalAccepted,
    RfpApprovalDecisionIn,
    RfpApprovalStarted,
    RfpDraftingAccepted,
    RfpFinalDocument,
    RfpTicketAccepted,
    RfpTicketDetail,
    RfpTicketList,
    RfpTicketSummary,
    RfpTraceList,
)

router = APIRouter(prefix="/rfp", tags=["rfp"])
logger = logging.getLogger("api.rfp")

ACCEPTED_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}
DATABASE_UNAVAILABLE = "La recepción de RFPs necesita PostgreSQL (DATABASE_URL de Supabase en .env)."


def get_rfp_store() -> RfpStore:
    if engine is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=DATABASE_UNAVAILABLE)
    return SqlRfpStore(engine)


def get_approval_service(store: Annotated[RfpStore, Depends(get_rfp_store)]) -> approval_runner.ApprovalService:
    try:
        return approval_runner.ApprovalService(store)
    except CheckpointerUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


def _approval_requests(store: RfpStore, ticket: dict[str, Any]) -> list[dict[str, Any]]:
    """Lo que espera cada rama interrumpida; vacío si el ticket no está en la Parte 3."""
    if ticket.get("status") != approval_config.STATUS_AWAITING:
        return []
    try:
        departments = [s["department_id"] for s in ticket.get("sections") or []]
        return approval_runner.ApprovalService(store).pending_requests(ticket["ticket_id"], departments)
    except Exception:  # sin checkpointer el detalle se sigue sirviendo
        logger.exception("No se pudieron leer las aprobaciones pendientes del ticket %s", ticket["ticket_id"])
        return []


def _summary(ticket: dict[str, Any]) -> RfpTicketSummary:
    return RfpTicketSummary(
        ticket_id=ticket["ticket_id"],
        rfp_id=ticket["rfp_id"],
        status=ticket["status"],
        stage=ticket["stage"],
        original_filename=ticket["original_filename"],
        client_name=ticket.get("client_name"),
        error_stage=ticket.get("error_stage"),
        ready_for_drafting=bool(ticket.get("ready_for_drafting")),
        ready_for_approval=bool(ticket.get("ready_for_approval")),
        stale=is_stale(ticket),
        created_at=ticket["created_at"],
        updated_at=ticket["updated_at"],
    )


@router.post("/tickets", response_model=RfpTicketAccepted, status_code=status.HTTP_202_ACCEPTED)
async def upload_rfp(
    request: Request,
    background_tasks: BackgroundTasks,
    user: Annotated[dict, Depends(get_current_user)],
    store: Annotated[RfpStore, Depends(get_rfp_store)],
    filename: Annotated[str | None, Query(max_length=200)] = None,
) -> RfpTicketAccepted:
    """Crea el ticket y lanza el pipeline en segundo plano. No espera a los agentes."""
    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Envía el PDF como cuerpo de la petición con Content-Type: application/pdf.",
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > rfp_config.MAX_PDF_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="El PDF es demasiado grande.")
    content = await request.body()
    try:
        # Escritura del PDF + INSERT: fuera del event loop, pero antes de responder.
        ticket = await run_in_threadpool(
            intake.accept_upload, content, filename, store, uploaded_by=str(user.get("id", "")) or None
        )
    except intake.UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)
    except Exception:
        logger.exception("No se pudo registrar la RFP")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No se pudo registrar la RFP.")

    background_tasks.add_task(runner.process_ticket_safely, ticket["ticket_id"], store)
    # Parte 2: las tareas de fondo corren en orden; solo arranca si la Parte 1 dejó el ticket en la cola.
    background_tasks.add_task(drafting_runner.draft_if_ready_safely, ticket["ticket_id"], store)
    # Parte 3: abre la aprobación humana si la Parte 2 dejó los borradores listos.
    background_tasks.add_task(approval_runner.start_if_ready_safely, ticket["ticket_id"], store)
    logger.info("RFP recibida: ticket %s (%s, %d bytes)", ticket["ticket_id"], ticket["original_filename"], len(content))
    return RfpTicketAccepted(
        ticket_id=ticket["ticket_id"],
        rfp_id=ticket["rfp_id"],
        status=ticket["status"],
        stage=ticket["stage"],
        original_filename=ticket["original_filename"],
        status_url=f"/rfp/tickets/{ticket['ticket_id']}",
    )


@router.get("/tickets", response_model=RfpTicketList)
def list_rfp_tickets(
    _: Annotated[dict, Depends(get_current_user)],
    store: Annotated[RfpStore, Depends(get_rfp_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> RfpTicketList:
    return RfpTicketList(tickets=[_summary(ticket) for ticket in store.list_tickets(limit)])


@router.get("/tickets/{ticket_id}", response_model=RfpTicketDetail)
def get_rfp_ticket(
    ticket_id: int,
    _: Annotated[dict, Depends(get_current_user)],
    store: Annotated[RfpStore, Depends(get_rfp_store)],
) -> RfpTicketDetail:
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe ese ticket de RFP.")
    return RfpTicketDetail(
        ticket_id=ticket["ticket_id"],
        rfp_id=ticket["rfp_id"],
        status=ticket["status"],
        stage=ticket["stage"],
        original_filename=ticket["original_filename"],
        raw_pdf_path=ticket["raw_pdf_path"],
        file_size_bytes=ticket["file_size_bytes"],
        markdown_chars=ticket.get("markdown_chars"),
        classification=ticket.get("classification"),
        metadata=ticket.get("metadata"),
        sections=ticket.get("sections") or [],
        handoff=ticket.get("handoff"),
        ready_for_drafting=bool(ticket.get("ready_for_drafting")),
        drafting_handoff=ticket.get("drafting_handoff"),
        ready_for_approval=bool(ticket.get("ready_for_approval")),
        approval_requests=_approval_requests(store, ticket),
        final_document_available=ticket.get("status") == approval_config.STATUS_DONE,
        error_stage=ticket.get("error_stage"),
        error_message=ticket.get("error_message"),
        stale=is_stale(ticket),
        created_at=ticket["created_at"],
        updated_at=ticket["updated_at"],
    )


@router.post("/tickets/{ticket_id}/drafts", response_model=RfpDraftingAccepted, status_code=status.HTTP_202_ACCEPTED)
def regenerate_rfp_drafts(
    ticket_id: int,
    background_tasks: BackgroundTasks,
    _: Annotated[dict, Depends(get_current_user)],
    store: Annotated[RfpStore, Depends(get_rfp_store)],
) -> RfpDraftingAccepted:
    """Parte 2: toma el ticket (atómico) y genera + evalúa sus secciones en segundo plano."""
    try:
        ticket = store.claim_for_drafting(ticket_id, force=True)
    except TicketNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe ese ticket de RFP.")
    except NotDraftable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"No se pueden generar los borradores: {exc}.")
    background_tasks.add_task(drafting_runner.draft_ticket_safely, ticket_id, store, claimed=True)
    background_tasks.add_task(approval_runner.start_if_ready_safely, ticket_id, store)
    logger.info("Borradores del ticket RFP %s relanzados", ticket_id)
    return RfpDraftingAccepted(
        ticket_id=ticket["ticket_id"],
        status=ticket["status"],
        stage=ticket["stage"],
        status_url=f"/rfp/tickets/{ticket['ticket_id']}",
    )


# --------------------------------------------------------------------------- #
# Parte 3 · aprobación humana por departamento y cierre del documento
# --------------------------------------------------------------------------- #
@router.post("/tickets/{ticket_id}/approvals", response_model=RfpApprovalStarted, status_code=status.HTTP_202_ACCEPTED)
def start_rfp_approval(
    ticket_id: int,
    background_tasks: BackgroundTasks,
    _: Annotated[dict, Depends(get_current_user)],
    store: Annotated[RfpStore, Depends(get_rfp_store)],
    # Sin checkpointer (falta `langgraph-checkpoint-sqlite`) responde 503 antes de tocar el ticket.
    _service: Annotated[approval_runner.ApprovalService, Depends(get_approval_service)],
) -> RfpApprovalStarted:
    """Abre (o reinicia desde cero) las ramas de aprobación del ticket en segundo plano."""
    try:
        ticket = store.claim_for_approval(ticket_id, force=True)
    except TicketNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe ese ticket de RFP.")
    except NotApprovable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"No se puede abrir la aprobación: {exc}.")
    background_tasks.add_task(approval_runner.start_safely, ticket_id, store, claimed=True)
    logger.info("Aprobación del ticket RFP %s abierta", ticket_id)
    return RfpApprovalStarted(ticket_id=ticket_id, status=ticket["status"], stage=ticket["stage"],
                              status_url=f"/rfp/tickets/{ticket_id}")


@router.post(
    "/tickets/{ticket_id}/approvals/{department_id}",
    response_model=RfpApprovalAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def decide_rfp_section(
    ticket_id: int,
    department_id: str,
    body: RfpApprovalDecisionIn,
    background_tasks: BackgroundTasks,
    _: Annotated[dict, Depends(get_current_user)],
    store: Annotated[RfpStore, Depends(get_rfp_store)],
    service: Annotated[approval_runner.ApprovalService, Depends(get_approval_service)],
) -> RfpApprovalAccepted:
    """Valida la decisión del responsable y reanuda solo la rama de ese departamento."""
    payload = body.model_dump()
    try:
        if body.decision == approval_config.DECISION_CHANGES:
            decision = service.submit(ticket_id, department_id, payload)
            background_tasks.add_task(approval_runner.resume_safely, ticket_id, department_id, decision, store)
            resumed = False
        else:
            service.decide(ticket_id, department_id, payload)
            resumed = True
    except TicketNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe ese ticket de RFP.")
    except approval_runner.InvalidDecision as exc:
        raise HTTPException(status_code=422, detail=f"Decisión no válida: {exc}")
    except NotApprovable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"No se puede registrar la decisión: {exc}.")
    ticket = store.get_ticket(ticket_id) or {}
    section = next((s for s in ticket.get("sections") or [] if s["department_id"] == department_id), {})
    logger.info("Ticket RFP %s · %s: %s de %s", ticket_id, department_id, body.decision, body.approver)
    return RfpApprovalAccepted(
        ticket_id=ticket_id, department_id=department_id, decision=body.decision,
        approval_status=section.get("approval_status"), status=ticket.get("status", ""), stage=ticket.get("stage", ""),
        resumed=resumed, status_url=f"/rfp/tickets/{ticket_id}",
    )


@router.get("/tickets/{ticket_id}/trace", response_model=RfpTraceList)
def get_rfp_trace(
    ticket_id: int,
    _: Annotated[dict, Depends(get_current_user)],
    store: Annotated[RfpStore, Depends(get_rfp_store)],
) -> RfpTraceList:
    if store.get_ticket(ticket_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No existe ese ticket de RFP.")
    return RfpTraceList(ticket_id=ticket_id, events=store.list_trace(ticket_id))


@router.get("/tickets/{ticket_id}/document", response_model=RfpFinalDocument)
def get_rfp_final_document(
    ticket_id: int,
    _: Annotated[dict, Depends(get_current_user)],
    store: Annotated[RfpStore, Depends(get_rfp_store)],
) -> RfpFinalDocument:
    document = store.get_final_document(ticket_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="El documento final se genera cuando todos los departamentos aprueban su sección.")
    return RfpFinalDocument.model_validate(document)
