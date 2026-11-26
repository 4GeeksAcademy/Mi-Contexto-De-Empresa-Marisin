"""Servicio de la Parte 3: abre las ramas de aprobación, reanuda con la decisión humana y cierra.

Entradas explícitas del flujo (ninguna reinicia el grafo desde cero salvo `start`):

- `start(ticket_id)`: toma el ticket de la cola de la Parte 2 (`ready_for_approval`,
  atómico) → `esperando_aprobación`, y ejecuta el grafo del ticket hasta su
  `interrupt`: arbitraje inicial, una rama por departamento (cada una hasta su
  propio `interrupt` en `human_approval`) y espera de sign-offs.
- `decide(ticket_id, department_id, payload)` = `submit` + `resume`: valida la
  respuesta humana **antes** de tocar el grafo (`ApprovalDecision`: decisión,
  aprobador = responsable del BRIEFING, motivo) y comprueba que esa rama está
  interrumpida; después `Command(resume=decisión)` sobre el hilo
  `rfp-{ticket_id}:{department_id}`. Solo se reanuda esa rama.
- Cuando una rama termina (aprobada o rechazada), `notify` reanuda el hilo del
  ticket `rfp-{ticket_id}` con su `SignoffEvent`; con todas aprobadas y sin
  conflictos, el grafo genera el documento final y el ticket pasa a `terminado`.

Concurrencia: un candado por hilo (en el proceso de la API). Las ramas se
ejecutan en hilos del sistema propios (`ThreadPoolExecutor`): así cada
`invoke` de una rama es una ejecución de primer nivel con su propio
`thread_id`, nunca un subgrafo del ticket (un `interrupt` de una rama no puede
pausar el grafo del ticket ni a otra rama).
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import config as intake_config
from ..llm import LLM
from ..store import NotApprovable, RfpStore, TicketNotFound
from . import config, nodes
from .checkpoint import delete_threads, get_checkpointer
from .schemas import ApprovalDecision, validate_decision
from .trace import TraceSink

logger = logging.getLogger("rfp_intake.approval.runner")

_registry_lock = threading.Lock()
_locks: dict[str, threading.RLock] = {}


def thread_lock(thread_id: str) -> threading.RLock:
    with _registry_lock:
        return _locks.setdefault(thread_id, threading.RLock())


class StoreTraceSink:
    def __init__(self, store: RfpStore) -> None:
        self.store = store

    def record(self, entry: dict[str, Any]) -> None:
        if entry.get("ticket_id") is None:
            return
        try:
            self.store.append_trace(entry["ticket_id"], entry)
        except Exception:  # la traza nunca rompe el flujo
            logger.exception("No se pudo guardar la traza del nodo %s", entry.get("node"))


class StoreApprovalReporter:
    """Persiste los avisos de los nodos de la Parte 3 en el ticket y sus secciones."""

    def __init__(self, store: RfpStore) -> None:
        self.store = store

    def approval_requested(self, ticket_id, department_id, section, *, round_number, requested_at):
        self.store.save_section_approval(
            ticket_id, department_id, approval_status=config.APPROVAL_PENDING, approval_round=round_number,
            approval_requested_at=requested_at, approver=None, approved_at=None,
        )
        # Tras una reescritura (humana o del árbitro) el ticket vuelve a esperar los vistos buenos.
        self.store.set_approval_progress(ticket_id, config.STAGE_AWAITING)

    def revising(self, ticket_id, department_id, *, round_number, feedback, decision=None):
        # La petición de cambios del responsable queda en el historial de la sección (las del árbitro las
        # registra `arbitration`): así `approval_history` tiene todas las decisiones, no solo el sign-off final.
        entry = None
        if decision:
            entry = {"approval_status": config.APPROVAL_CHANGES, "decision": decision["decision"],
                     "approver": decision["approver"], "comment": decision.get("comment") or "",
                     "round": round_number, "decided_at": decision.get("decided_at")}
        self.store.save_section_approval(
            ticket_id, department_id, approval_status=config.APPROVAL_CHANGES, approval_comment=feedback[:2000],
            decision_entry=entry,
        )
        self.store.set_approval_progress(ticket_id, config.STAGE_REVISING)

    def revision_progress(self, ticket_id, department_id, **changes):
        self.store.save_section_draft(ticket_id, department_id, **changes)

    def signoff(self, ticket_id, department_id, event):
        approved = event["approval_status"] == config.APPROVAL_APPROVED
        self.store.save_section_approval(
            ticket_id, department_id, approval_status=event["approval_status"], approver=event["approver"],
            approved_at=event["decided_at"] if approved else None, approval_comment=event["comment"] or None,
            approval_round=event["rounds"],
            decision_entry={k: event[k] for k in ("approval_status", "approver", "decided_at", "comment", "reason", "rounds")},
        )

    def arbitration(self, ticket_id, decisions, rejected):
        self.store.set_approval_progress(ticket_id, config.STAGE_ARBITRATING)
        for department_id in {d for decision in decisions for d in decision["departments"]}:
            entries = [d for d in decisions if department_id in d["departments"]]
            for entry in entries:
                self.store.save_section_approval(ticket_id, department_id, decision_entry={
                    "arbitration": entry["trigger"], "arbiter": entry["arbiter"], "action": entry["action"],
                    "round": entry["round"], "detail": entry["detail"], "decided_at": entry["decided_at"],
                })

    def awaiting(self, ticket_id, pending):
        self.store.set_approval_progress(ticket_id, config.STAGE_AWAITING)

    def closing(self, ticket_id):
        self.store.set_approval_progress(ticket_id, config.STAGE_CLOSING)

    def final_document(self, ticket_id, document):
        self.store.save_final_document(ticket_id, document)

    def rejected(self, ticket_id, rejected, blocked):
        for department_id, reason in rejected.items():
            self.store.save_section_approval(
                ticket_id, department_id, approval_status=config.APPROVAL_REJECTED, approval_comment=reason[:2000],
            )
        self.store.set_approval_progress(ticket_id, config.STAGE_REJECTED)


class InvalidDecision(ValueError):
    """La respuesta humana no pasa la validación: no entra al grafo."""


class ApprovalService:
    def __init__(
        self,
        store: RfpStore,
        *,
        llm: LLM | None = None,
        checkpointer=None,
        sink: TraceSink | None = None,
        reporter=None,
    ) -> None:
        from .graph import build_department_graph, build_ticket_graph

        self.store = store
        self.checkpointer = checkpointer if checkpointer is not None else get_checkpointer()
        self.sink = sink or StoreTraceSink(store)
        self.reporter = reporter or StoreApprovalReporter(store)
        self.department_graph = build_department_graph(
            llm=llm, reporter=self.reporter, sink=self.sink, checkpointer=self.checkpointer
        )
        self.ticket_graph = build_ticket_graph(
            branches=self, reporter=self.reporter, sink=self.sink, checkpointer=self.checkpointer
        )

    # ------------------------------------------------------------------ #
    # Estado de los hilos
    # ------------------------------------------------------------------ #
    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": config.RECURSION_LIMIT}

    def branch_snapshot(self, ticket_id: int, department_id: str):
        return self.department_graph.get_state(self._config(config.department_thread_id(ticket_id, department_id)))

    def ticket_snapshot(self, ticket_id: int):
        return self.ticket_graph.get_state(self._config(config.ticket_thread_id(ticket_id)))

    @staticmethod
    def _interrupts(snapshot) -> list[Any]:
        return [item.value for task in (getattr(snapshot, "tasks", None) or ()) for item in (task.interrupts or ())]

    def branch_waiting(self, ticket_id: int, department_id: str) -> bool:
        snapshot = self.branch_snapshot(ticket_id, department_id)
        return nodes.NODE_HUMAN in (snapshot.next or ()) and bool(self._interrupts(snapshot))

    def ticket_waiting(self, ticket_id: int) -> bool:
        snapshot = self.ticket_snapshot(ticket_id)
        return nodes.NODE_AWAIT in (snapshot.next or ()) and bool(self._interrupts(snapshot))

    def pending_requests(self, ticket_id: int, departments: list[str] | None = None) -> list[dict[str, Any]]:
        """`ApprovalRequest` de cada rama interrumpida (lo que ve el responsable)."""
        requests = []
        for department_id in departments or intake_config.DEPARTMENT_ORDER:
            snapshot = self.branch_snapshot(ticket_id, department_id)
            if nodes.NODE_HUMAN in (snapshot.next or ()):
                requests += [value for value in self._interrupts(snapshot) if isinstance(value, dict)]
        return requests

    def summary(self, ticket_id: int) -> dict[str, Any]:
        ticket = self.store.get_ticket(ticket_id) or {}
        branches = {}
        for section in ticket.get("sections") or []:
            department_id = section["department_id"]
            branches[department_id] = {
                "thread_id": config.department_thread_id(ticket_id, department_id),
                "waiting": self.branch_waiting(ticket_id, department_id),
                "approval_status": section.get("approval_status"),
            }
        snapshot = self.ticket_snapshot(ticket_id)
        return {
            "ticket_id": ticket_id,
            "status": ticket.get("status"),
            "stage": ticket.get("stage"),
            "thread_id": config.ticket_thread_id(ticket_id),
            "ticket_waiting": self.ticket_waiting(ticket_id),
            "pending": list((snapshot.values or {}).get("pending") or []),
            "outcome": (snapshot.values or {}).get("outcome"),
            "branches": branches,
        }

    # ------------------------------------------------------------------ #
    # Arranque
    # ------------------------------------------------------------------ #
    def start(self, ticket_id: int, *, force: bool = False, claimed: bool = False) -> dict[str, Any]:
        """Abre la aprobación del ticket. Lanza `NotApprovable` si no puede empezar."""
        if not claimed:
            self.store.claim_for_approval(ticket_id, force=force)
        ticket = self.store.get_ticket(ticket_id)
        if ticket is None:
            raise TicketNotFound(ticket_id)
        threads = [config.ticket_thread_id(ticket_id)] + [
            config.department_thread_id(ticket_id, d) for d in intake_config.DEPARTMENT_ORDER
        ]
        created_at = ticket.get("created_at")
        with thread_lock(config.ticket_thread_id(ticket_id)):
            delete_threads(self.checkpointer, threads)  # una aprobación nueva nunca hereda un checkpoint viejo
            try:
                self.ticket_graph.invoke(
                    {
                        "ticket_id": ticket_id,
                        "rfp_id": ticket.get("rfp_id"),
                        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
                        "drafting_handoff": ticket.get("drafting_handoff") or {},
                        "handoff": ticket.get("handoff") or {},
                    },
                    self._config(config.ticket_thread_id(ticket_id)),
                )
            except Exception as exc:
                logger.exception("Aprobación del ticket RFP %s: fallo al abrir las ramas", ticket_id)
                self.store.fail(ticket_id, (self.store.get_ticket(ticket_id) or {}).get("stage") or config.STAGE_AWAITING,
                                f"{type(exc).__name__}: {exc}")
                raise
        return self.summary(ticket_id)

    def start_many(self, ticket_id: int, inputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Arranca (o reabre) ramas en paralelo; cada una corre hasta su `interrupt` o su final."""
        if not inputs:
            return {}
        with ThreadPoolExecutor(max_workers=len(inputs), thread_name_prefix=f"rfp-{ticket_id}") as pool:
            futures = {d: pool.submit(self._run_branch, ticket_id, d, payload) for d, payload in inputs.items()}
            return {d: future.result() for d, future in futures.items()}

    def _run_branch(self, ticket_id: int, department_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        thread_id = config.department_thread_id(ticket_id, department_id)
        with thread_lock(thread_id):
            self.department_graph.invoke(payload, self._config(thread_id))
            return self._branch_result(ticket_id, department_id)

    def _branch_result(self, ticket_id: int, department_id: str) -> dict[str, Any]:
        snapshot = self.branch_snapshot(ticket_id, department_id)
        waiting = nodes.NODE_HUMAN in (snapshot.next or ())
        signoff = None if waiting else (snapshot.values or {}).get("signoff")
        return {"waiting": waiting, "signoff": signoff}

    # ------------------------------------------------------------------ #
    # Decisión humana → resume
    # ------------------------------------------------------------------ #
    def _check_can_decide(self, ticket_id: int, department_id: str) -> dict[str, Any]:
        ticket = self.store.get_ticket(ticket_id)
        if ticket is None:
            raise TicketNotFound(ticket_id)
        if ticket.get("status") != config.STATUS_AWAITING:
            raise NotApprovable(f"el ticket está en «{ticket.get('status')}», no esperando aprobación")
        if ticket.get("stage") == config.STAGE_REJECTED:
            raise NotApprovable("el ticket tiene una sección rechazada: regenera los borradores (nueva ejecución)")
        section = next((s for s in ticket.get("sections") or [] if s["department_id"] == department_id), None)
        if section is None:
            raise NotApprovable(f"el departamento {department_id} no participa en esta RFP")
        if section.get("approval_status") != config.APPROVAL_PENDING or not self.branch_waiting(ticket_id, department_id):
            raise NotApprovable(f"la sección de {department_id} no está esperando aprobación "
                                f"(estado: {section.get('approval_status') or '—'})")
        return section

    def submit(self, ticket_id: int, department_id: str, payload: Any) -> ApprovalDecision:
        """Valida la respuesta y reserva la rama. No reanuda nada."""
        if department_id not in intake_config.DEPARTMENTS:
            raise NotApprovable(f"departamento desconocido: {department_id}")
        try:
            decision = validate_decision(payload, department_id)
        except Exception as exc:  # pydantic.ValidationError (o un payload que no es un objeto)
            raise InvalidDecision(_validation_message(exc)) from exc
        with thread_lock(config.department_thread_id(ticket_id, department_id)):
            self._check_can_decide(ticket_id, department_id)
            if decision.decision == config.DECISION_CHANGES:
                # Reserva la rama: un segundo envío mientras se reescribe recibe 409.
                self.store.save_section_approval(ticket_id, department_id, approval_status=config.APPROVAL_CHANGES,
                                                 approval_comment=decision.comment)
        return decision

    def _resume_branch(self, ticket_id: int, department_id: str, decision: ApprovalDecision) -> dict[str, Any] | None:
        """`Command(resume=decisión)` sobre la rama. Devuelve su `SignoffEvent` si terminó."""
        from langgraph.types import Command

        thread_id = config.department_thread_id(ticket_id, department_id)
        with thread_lock(thread_id):
            if not self.branch_waiting(ticket_id, department_id):
                raise NotApprovable(f"la sección de {department_id} no está esperando aprobación")
            try:
                self.department_graph.invoke(Command(resume=decision.model_dump()), self._config(thread_id))
            except Exception as exc:
                logger.exception("Rama %s: fallo al reanudar", thread_id)
                self.store.fail(ticket_id, config.STAGE_REVISING, f"{type(exc).__name__}: {exc}")
                raise
            return self._branch_result(ticket_id, department_id)["signoff"]

    def resume(self, ticket_id: int, department_id: str, decision: ApprovalDecision) -> dict[str, Any]:
        """Reanuda solo esa rama y, si termina, avisa al ticket (sin retener el candado de la rama)."""
        signoff = self._resume_branch(ticket_id, department_id, decision)
        if signoff:
            # Fuera del candado de la rama: el ticket puede reabrirla (arbitraje) desde otro hilo.
            self.notify(ticket_id, signoff)
        return self.summary(ticket_id)

    def decide(self, ticket_id: int, department_id: str, payload: Any) -> dict[str, Any]:
        """Validar + reanudar en la misma llamada (CLI, tests y aprobar/rechazar desde la API)."""
        thread_id = config.department_thread_id(ticket_id, department_id)
        with thread_lock(thread_id):  # nadie más decide en esta rama entre la validación y el resume
            decision = self.submit(ticket_id, department_id, payload)
            signoff = self._resume_branch(ticket_id, department_id, decision)
        if signoff:
            self.notify(ticket_id, signoff)
        return self.summary(ticket_id)

    def notify(self, ticket_id: int, signoff: dict[str, Any]) -> None:
        """Reanuda el hilo del ticket con el sign-off de una rama terminada."""
        from langgraph.types import Command

        with thread_lock(config.ticket_thread_id(ticket_id)):
            if not self.ticket_waiting(ticket_id):
                logger.warning("Ticket RFP %s: sign-off de %s sin espera pendiente", ticket_id, signoff.get("department_id"))
                return
            try:
                self.ticket_graph.invoke(Command(resume=signoff), self._config(config.ticket_thread_id(ticket_id)))
            except Exception as exc:
                logger.exception("Ticket RFP %s: fallo al cerrar tras el sign-off", ticket_id)
                self.store.fail(ticket_id, config.STAGE_CLOSING, f"{type(exc).__name__}: {exc}")
                raise


def _validation_message(exc: Exception) -> str:
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            return "; ".join(
                f"{'.'.join(str(p) for p in e.get('loc', ()) if p != '__root__') or 'decisión'}: "
                f"{str(e.get('msg', '')).removeprefix('Value error, ')}"
                for e in errors()
            )
        except Exception:
            pass
    return str(exc)


# --------------------------------------------------------------------------- #
# Entradas para BackgroundTasks (nunca dejan escapar una excepción)
# --------------------------------------------------------------------------- #
def start_if_ready_safely(ticket_id: int, store: RfpStore, **kwargs: Any) -> None:
    """Encadena la Parte 3 tras la Parte 2 si el ticket quedó en su cola (`RFP_AUTO_APPROVAL`)."""
    if not config.AUTO_APPROVAL:
        return
    try:
        ticket = store.get_ticket(ticket_id)
        if not ticket or not ticket.get("ready_for_approval"):
            return
        ApprovalService(store, **kwargs).start(ticket_id)
    except NotApprovable as exc:
        logger.info("Ticket RFP %s no pasa a la Parte 3: %s", ticket_id, exc)
    except Exception:
        logger.exception("No se pudo abrir la aprobación del ticket RFP %s", ticket_id)


def start_safely(ticket_id: int, store: RfpStore, **kwargs: Any) -> None:
    try:
        ApprovalService(store, **{k: v for k, v in kwargs.items() if k != "claimed"}).start(
            ticket_id, claimed=kwargs.get("claimed", False)
        )
    except Exception:
        logger.exception("No se pudo abrir la aprobación del ticket RFP %s", ticket_id)


def resume_safely(ticket_id: int, department_id: str, decision: ApprovalDecision, store: RfpStore, **kwargs: Any) -> None:
    try:
        ApprovalService(store, **kwargs).resume(ticket_id, department_id, decision)
    except Exception:
        logger.exception("No se pudo reanudar la rama %s del ticket RFP %s", department_id, ticket_id)
