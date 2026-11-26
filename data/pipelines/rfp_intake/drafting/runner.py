"""Ejecuta la Parte 2 sobre un ticket y persiste cada paso en tiempo real.

Entrada: un ticket que la Parte 1 dejó en `analisis_completo` con
`ready_for_drafting = true` y su `handoff` (`trackflow.rfp_intake.handoff/v1`).
Nunca lee el PDF ni el Markdown.

1. `claim_for_drafting`: toma el ticket de la cola de forma atómica →
   `generando_borrador` / `generando_secciones` y baja la bandera (nadie más lo coge).
2. Grafo `rfp_drafting`; `StoreReporter` guarda en cuanto ocurre cada borrador
   (`draft_status = generando_borrador → en_evaluación`), cada `EvaluationResult`
   (+ su entrada de historial) y el estado final de la sección. Con el primer
   borrador el ticket pasa a `en_evaluación` / `evaluando_secciones`.
3. Final: `needs_human_review` si alguna sección agotó el límite; si no, sigue en
   `en_evaluación` con `stage = borradores_listos` (la Parte 3 escribirá
   `esperando_aprobación`). En ambos casos `drafting_handoff` + `ready_for_approval`.
4. Si algo falla: `stage = error` con `error_stage`; lo ya generado queda
   guardado y se relanza con `POST /rfp/tickets/{id}/drafts` o el CLI.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..approval.trace import record_safely, runner_entry
from ..llm import LLM
from ..store import NotDraftable, RfpStore, TicketNotFound
from . import config

logger = logging.getLogger("rfp_intake.drafting.runner")


@dataclass
class DraftingResult:
    ticket_id: int
    outcome: str  # "drafts_ready" | "needs_human_review" | "error"
    stage: str
    duration_ms: int
    sections: dict[str, str] = field(default_factory=dict)  # department_id → draft_status
    iterations: dict[str, int] = field(default_factory=dict)
    error: str | None = None


class StoreReporter:
    """Persiste los avisos de los nodos. Seguro con departamentos en paralelo."""

    def __init__(self, store: RfpStore, ticket_id: int) -> None:
        self.store = store
        self.ticket_id = ticket_id
        self.stage = config.STAGE_GENERATING
        self._lock = threading.Lock()

    def generating(self, department_id, iteration):
        self.store.save_section_draft(
            self.ticket_id, department_id, draft_status=config.SECTION_GENERATING, iterations=iteration
        )

    def _trace(self, node, agent, department_id, input=None, output=None):
        record_safely(self.store, runner_entry(graph=config.GRAPH_NAME, node=node, agent=agent,
                                               ticket_id=self.ticket_id, department_id=department_id,
                                               input=input, output=output))

    def drafted(self, department_id, draft):
        self._trace("generate", f"{department_id}_generator", department_id, {"iteration": draft["iteration"]},
                    {"source": draft["source"], "content": draft["content"]})
        self.store.save_section_draft(
            self.ticket_id,
            department_id,
            draft_status=config.SECTION_EVALUATING,
            draft_content=draft["content"],
            draft_source=draft["source"],
            iterations=draft["iteration"],
        )
        with self._lock:
            if self.stage != config.STAGE_EVALUATING:
                self.stage = config.STAGE_EVALUATING
                self.store.set_drafting_progress(self.ticket_id, config.STATUS_EVALUATING, config.STAGE_EVALUATING)

    def evaluated(self, department_id, evaluation, history_entry):
        self._trace("judge", "evaluators (legibilidad, pertinencia, cumplimiento) + judge", department_id,
                    {"iteration": evaluation.get("iteration")},
                    {"overall_pass": evaluation.get("overall_pass"), "violations": history_entry.get("violations"),
                     "missing_aspects": history_entry.get("missing_aspects")})
        self.store.save_section_draft(
            self.ticket_id, department_id, evaluation_results=evaluation, history_entry=history_entry
        )

    def finished(self, department_id, section):
        self._trace("finalize", "drafting_coordinator", department_id, {"iterations": section["iterations"]},
                    {"draft_status": section["draft_status"]})
        self.store.save_section_draft(
            self.ticket_id,
            department_id,
            draft_status=section["draft_status"],
            draft_content=section["draft_content"],
            iterations=section["iterations"],
        )


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def draft_ticket(
    ticket_id: int,
    store: RfpStore,
    *,
    llm: LLM | None = None,
    force: bool = False,
    claimed: bool = False,
    graph=None,
) -> DraftingResult:
    """Genera y evalúa las secciones de un ticket. Lanza `NotDraftable` si no puede empezar."""
    from .graph import build_graph

    started = time.perf_counter()
    if claimed:
        ticket = store.get_ticket(ticket_id)
        if ticket is None:
            raise TicketNotFound(ticket_id)
    else:
        ticket = store.claim_for_drafting(ticket_id, force=force)
    reporter = StoreReporter(store, ticket_id)
    try:
        compiled = graph or build_graph(llm, reporter)
        final = compiled.invoke({"ticket_id": ticket_id, "handoff": ticket.get("handoff"), "sections": []})
        output = final["output"]
        store.complete_drafting(ticket_id, output)
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        logger.exception("Borradores del ticket RFP %s: fallo en la etapa %s", ticket_id, reporter.stage)
        store.fail(ticket_id, reporter.stage, message)
        return DraftingResult(ticket_id, "error", reporter.stage, _elapsed(started), error=message)
    sections = {s["department_id"]: s["draft_status"] for s in output["sections"]}
    iterations = {s["department_id"]: s["iterations"] for s in output["sections"]}
    outcome = "needs_human_review" if output["needs_human_review"] else "drafts_ready"
    result = DraftingResult(ticket_id, outcome, config.STAGE_DRAFTS_READY, _elapsed(started), sections, iterations)
    logger.info("Ticket RFP %s → %s en %d ms (iteraciones %s)", ticket_id, outcome, result.duration_ms, iterations)
    return result


def draft_ticket_safely(ticket_id: int, store: RfpStore, **kwargs: Any) -> None:
    """Entrada para `BackgroundTasks`: nunca deja escapar una excepción."""
    try:
        draft_ticket(ticket_id, store, **kwargs)
    except NotDraftable as exc:
        logger.info("Ticket RFP %s no pasa a la Parte 2: %s", ticket_id, exc)
    except Exception:
        logger.exception("No se pudieron generar los borradores del ticket RFP %s", ticket_id)


def draft_if_ready_safely(ticket_id: int, store: RfpStore, **kwargs: Any) -> None:
    """Encadena la Parte 2 tras la Parte 1 si el ticket quedó en la cola (`RFP_AUTO_DRAFT`)."""
    if not config.AUTO_DRAFT:
        return
    try:
        ticket = store.get_ticket(ticket_id)
    except Exception:
        logger.exception("No se pudo leer el ticket RFP %s para la Parte 2", ticket_id)
        return
    if not ticket or not ticket.get("ready_for_drafting"):
        return  # descartado, con error o sin departamentos: la Parte 2 no arranca
    draft_ticket_safely(ticket_id, store, **kwargs)


def draft_pending(store: RfpStore, *, llm: LLM | None = None, limit: int = 50) -> list[DraftingResult]:
    """Procesa la cola de la Parte 2 (CLI `--pending`)."""
    results = []
    for ticket in store.list_ready_for_drafting(limit):
        try:
            results.append(draft_ticket(ticket["ticket_id"], store, llm=llm))
        except NotDraftable as exc:  # otro proceso lo tomó entre la lista y el claim
            logger.info("Ticket RFP %s omitido: %s", ticket["ticket_id"], exc)
    return results
