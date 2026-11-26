"""Nodos de los grafos de la Parte 3. Funciones (estado, dependencias) → actualización.

Rama de un departamento (`rfp_department_approval`, hilo `rfp-{ticket}:{dept}`):

- `prepare_review`: arranca o reabre la rama (con o sin cambios forzados por el árbitro).
- `revise_section`: vuelve al generador de la Parte 2 **del mismo departamento** con
  el feedback humano o del árbitro y lo reevalúa con los tres evaluadores
  (`rfp_section_loop`): no es una ejecución nueva del flujo (pregunta de diseño 1).
- `request_approval`: guarda la sección como `pendiente` y la hora (KPI §3).
- `human_approval`: `interrupt(ApprovalRequest)` — la rama se detiene aquí, con su
  estado en el checkpointer, hasta que `Command(resume=decisión)` la reanuda.
  La decisión ya llega validada; si aun así no es válida, se vuelve a pedir.
- `record_signoff`: aprobada o rechazada (por el humano o por el límite de rondas).

Ticket (`rfp_approval`, hilo `rfp-{ticket}`):

- `load_drafts` → `detect_conflicts` → (`arbitrate`) → `open_branches` →
  `await_signoffs` (⟲ `interrupt` hasta que no quede ninguna rama pendiente) →
  `detect_conflicts` otra vez sobre lo aprobado → `close_document` (o `arbitrate`
  y reabrir las secciones ofensoras, o `reject_ticket`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from .. import config as intake_config
from ..drafting import config as drafting_config
from ..drafting import handoff as drafting_handoff
from ..drafting.schemas import DraftingInput
from ..llm import LLM
from . import config
from .arbiter import arbitrate
from .conflicts import detect_conflicts
from .document import build_final_document
from .reporter import ApprovalReporter, NullApprovalReporter
from .schemas import ApprovalRequest, SignoffEvent, validate_decision
from .trace import summarize, utc_iso

try:  # LangGraph real; el import se hace aquí para que los módulos puros no lo necesiten.
    from langgraph.types import interrupt
except ModuleNotFoundError:  # pragma: no cover - solo sin langgraph instalado
    def interrupt(value):
        raise RuntimeError("La Parte 3 necesita langgraph")

# Rama de departamento
NODE_PREPARE = "prepare_review"
NODE_REVISE = "revise_section"
NODE_REQUEST = "request_approval"
NODE_HUMAN = "human_approval"
NODE_SIGNOFF = "record_signoff"
DEPARTMENT_NODES = (NODE_PREPARE, NODE_REVISE, NODE_REQUEST, NODE_HUMAN, NODE_SIGNOFF)

# Ticket
NODE_LOAD = "load_drafts"
NODE_DETECT = "detect_conflicts"
NODE_ARBITRATE = "arbitrate"
NODE_OPEN = "open_branches"
NODE_AWAIT = "await_signoffs"
NODE_CLOSE = "close_document"
NODE_REJECT = "reject_ticket"
TICKET_NODES = (NODE_LOAD, NODE_DETECT, NODE_ARBITRATE, NODE_OPEN, NODE_AWAIT, NODE_CLOSE, NODE_REJECT)

PHASE_OPENING = "opening"
PHASE_CLOSING = "closing"


class Branches(Protocol):
    """Arranca (o reabre) ramas de departamento. Lo implementa `runner.ApprovalService`."""

    def start_many(self, ticket_id: int, inputs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]: ...


@dataclass
class Deps:
    llm: LLM | None = None
    reporter: ApprovalReporter = field(default_factory=NullApprovalReporter)
    branches: Branches | None = None


# --------------------------------------------------------------------------- #
# Rama de un departamento
# --------------------------------------------------------------------------- #
def prepare_review(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    if not (state.get("section") or {}).get("draft_content"):
        raise ValueError(f"La sección de {state.get('department_id')} no tiene borrador de la Parte 2.")
    return {
        "round": int(state.get("round") or 0),
        "max_rounds": int(state.get("max_rounds") or config.MAX_APPROVAL_ROUNDS),
        "decision": None,
        "signoff": None,
        "outcome": None,
    }


def route_after_prepare(state: dict[str, Any]) -> str:
    if state.get("forced"):
        return NODE_REVISE if state["round"] < state["max_rounds"] else NODE_SIGNOFF
    return NODE_REQUEST


class _RevisionDrafts:
    """Reporter de la Parte 2 que solo guarda la sección (no cambia el estado del ticket)."""

    def __init__(self, reporter: ApprovalReporter, ticket_id: int | None) -> None:
        self.reporter = reporter
        self.ticket_id = ticket_id

    def generating(self, department_id, iteration):
        self.reporter.revision_progress(self.ticket_id, department_id, draft_status=drafting_config.SECTION_GENERATING)

    def drafted(self, department_id, draft):
        self.reporter.revision_progress(self.ticket_id, department_id, draft_status=drafting_config.SECTION_EVALUATING,
                                        draft_content=draft["content"], draft_source=draft["source"])

    def evaluated(self, department_id, evaluation, history_entry):
        self.reporter.revision_progress(self.ticket_id, department_id, evaluation_results=evaluation,
                                        history_entry={**history_entry, "phase": "approval"})

    def finished(self, department_id, section):
        pass


def revision_feedback(state: dict[str, Any]) -> str:
    parts = [change["feedback"] for change in state.get("forced") or []]
    decision = state.get("decision") or {}
    if decision.get("decision") == config.DECISION_CHANGES:
        parts.append(f"{decision['approver']} (responsable de {state['department_id']}) pide cambios: {decision['comment']}")
    return "\n".join(f"- {part}" for part in parts)


def revise_section(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    from ..drafting.graph import SECTION_RECURSION_LIMIT, build_section_graph

    department_id = state["department_id"]
    round_number = int(state.get("round") or 0) + 1
    context = dict(state["context"])
    for change in state.get("forced") or []:
        context.update(change.get("context_overrides") or {})
    model = DraftingInput.model_validate(context)
    section = state["section"]
    feedback = revision_feedback(state)
    deps.reporter.revising(state.get("ticket_id"), department_id, round_number=round_number, feedback=feedback)
    loop = build_section_graph(deps.llm, _RevisionDrafts(deps.reporter, state.get("ticket_id")), checkpointer=False)
    result = loop.invoke(
        {
            "ticket_id": state.get("ticket_id"),
            "department_id": department_id,
            "context": model.model_dump(mode="json"),
            "sources": drafting_handoff.anchor_sources(model),
            "max_iterations": drafting_config.MAX_ITERATIONS,
            "iteration": 0,
            # El generador recibe el borrador actual y el feedback como en un reintento de la Parte 2.
            "draft": {"department_id": department_id, "iteration": max(1, int(section.get("iterations") or 1)),
                      "content": section["draft_content"], "source": section.get("draft_source") or "rules"},
            "evaluation": {"feedback_for_generator": feedback},
            "checks": {},
            "history": [],
        },
        {"recursion_limit": SECTION_RECURSION_LIMIT},
    )
    final = result["final"]
    revised = {
        "draft_content": final["draft_content"],
        "draft_status": final["draft_status"],
        "iterations": final["iterations"],
        "draft_source": final["draft_source"],
        "evaluation_result": final["evaluation_result"],
        "provisional": final["provisional"],
    }
    deps.reporter.revision_progress(
        state.get("ticket_id"), department_id, draft_content=revised["draft_content"],
        draft_status=revised["draft_status"], iterations=revised["iterations"],
        draft_source=revised["draft_source"], evaluation_results=revised["evaluation_result"],
    )
    notes = list(state.get("arbitration_notes") or [])
    notes += [f"{c['arbiter']} · {c['trigger']}: reescritura forzada (ronda {round_number})" for c in state.get("forced") or []]
    return {
        "section": revised,
        "context": model.model_dump(mode="json"),
        "forced": [],
        "round": round_number,
        "arbitration_notes": notes,
        "revisions": [{
            "round": round_number,
            "triggers": [c["trigger"] for c in state.get("forced") or []],
            "requested_by": [c["arbiter"] for c in state.get("forced") or []]
            + ([(state.get("decision") or {}).get("approver")] if (state.get("decision") or {}).get("decision") else []),
            "feedback": feedback,
            "iterations": final["iterations"],
            "overall_pass": final["evaluation_result"]["overall_pass"],
            "at": utc_iso(),
        }],
    }


def request_approval(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    requested_at = utc_iso()
    deps.reporter.approval_requested(state.get("ticket_id"), state["department_id"], state["section"],
                                     round_number=int(state.get("round") or 0), requested_at=requested_at)
    return {"approval_requested_at": requested_at, "decision": None}


def approval_request(state: dict[str, Any]) -> dict[str, Any]:
    """Lo mínimo que necesita el responsable para decidir (pregunta de diseño 2)."""
    section = state["section"]
    evaluation = section.get("evaluation_result") or {}
    decisions = [d for d in state.get("decisions") or [] if d.get("decision")]
    return ApprovalRequest(
        ticket_id=state.get("ticket_id"),
        department_id=state["department_id"],
        department_name=state["department_name"],
        responsible=state["responsible"],
        round=int(state.get("round") or 0),
        max_rounds=int(state.get("max_rounds") or config.MAX_APPROVAL_ROUNDS),
        client_name=state.get("client_name"),
        currency=state.get("currency"),
        draft_status=section.get("draft_status"),
        provisional=bool(section.get("provisional")),
        iterations=int(section.get("iterations") or 0),
        overall_pass=evaluation.get("overall_pass"),
        violations=[v.get("rule_id", "") for v in (evaluation.get("compliance") or {}).get("violations") or []],
        missing_aspects=list((evaluation.get("relevance") or {}).get("missing_aspects") or []),
        arbitration_notes=list(state.get("arbitration_notes") or []),
        last_comment=decisions[-1].get("comment") if decisions else None,
    ).model_dump()


def human_approval(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    # Nada antes del interrupt tiene efectos: al reanudar, LangGraph vuelve a ejecutar el nodo entero.
    raw = interrupt(approval_request(state))
    try:
        decision = validate_decision(raw, state["department_id"])
    except (ValidationError, ValueError, TypeError) as exc:
        return {"decision": None, "decisions": [{"invalid": True, "error": str(exc)[:300], "received": summarize(raw)}]}
    entry = {**decision.model_dump(), "decided_at": utc_iso(), "round": int(state.get("round") or 0)}
    return {"decision": entry, "decisions": [entry]}


def route_after_human(state: dict[str, Any]) -> str:
    decision = state.get("decision")
    if not decision:
        return NODE_HUMAN  # respuesta inválida: se vuelve a pedir, el grafo no avanza
    if decision["decision"] == config.DECISION_CHANGES:
        return NODE_REVISE if state["round"] < state["max_rounds"] else NODE_SIGNOFF
    return NODE_SIGNOFF


def record_signoff(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    decision = state.get("decision") or {}
    forced = state.get("forced") or []
    section = state["section"]
    kind = decision.get("decision")
    if kind == config.DECISION_APPROVE:
        status, reason, approver = config.APPROVAL_APPROVED, "human", decision["approver"]
    elif kind == config.DECISION_REJECT:
        status, reason, approver = config.APPROVAL_REJECTED, "human", decision["approver"]
    elif kind == config.DECISION_CHANGES:  # pidió cambios con las rondas agotadas
        status, reason, approver = config.APPROVAL_REJECTED, "round-limit", decision["approver"]
    elif forced:  # el árbitro forzó cambios con las rondas agotadas
        status, reason, approver = config.APPROVAL_REJECTED, "round-limit", forced[0]["arbiter"]
    else:
        raise ValueError("record_signoff sin decisión")
    comment = decision.get("comment") or ""
    if reason == "round-limit":
        comment = (f"Límite de {state['max_rounds']} rondas de revisión agotado. " + comment).strip()
    event = SignoffEvent(
        department_id=state["department_id"], approval_status=status, approver=approver,
        decided_at=decision.get("decided_at") or utc_iso(), comment=comment, reason=reason,
        rounds=int(state.get("round") or 0), draft_content=section["draft_content"],
        draft_status=section.get("draft_status"), iterations=int(section.get("iterations") or 0),
        approval_requested_at=state.get("approval_requested_at"),
    ).model_dump()
    deps.reporter.signoff(state.get("ticket_id"), state["department_id"], event)
    return {"signoff": event, "outcome": status, "forced": []}


# --------------------------------------------------------------------------- #
# Ticket
# --------------------------------------------------------------------------- #
def load_drafts(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    output = state.get("drafting_handoff") or {}
    if output.get("contract") != config.INPUT_CONTRACT:
        raise ValueError(f"Contrato de handoff desconocido: {output.get('contract')!r} (se espera {config.INPUT_CONTRACT}).")
    if not output.get("ready_for_approval") or not output.get("sections"):
        raise ValueError("El handoff de la Parte 2 no tiene secciones listas para aprobación.")
    sections = {}
    for section in output["sections"]:
        if section["department_id"] not in intake_config.DEPARTMENTS:
            raise ValueError(f"Departamento desconocido: {section['department_id']}")
        sections[section["department_id"]] = {
            "department_name": section["department_name"],
            "responsible": intake_config.DEPARTMENTS[section["department_id"]].responsible,  # siempre del BRIEFING
            "draft_content": section["draft_content"],
            "draft_status": section["draft_status"],
            "iterations": section["iterations"],
            "draft_source": section.get("draft_source"),
            "evaluation_result": section.get("evaluation_result") or {},
            "provisional": bool(section.get("provisional")),
        }
    departments = [d for d in intake_config.DEPARTMENT_ORDER if d in sections]
    client = output.get("client") or {}
    return {
        "sections": sections,
        "departments": departments,
        "client": client,
        "currency": output.get("currency") or client.get("currency"),
        "monthly_volume": (state.get("handoff") or {}).get("monthly_volume"),
        "phase": PHASE_OPENING,
        "arbitration_round": 0,
        "conflicts": [],
        "forced": {},
        "overrides": {},
        "blocked": [],
        "rejected": {},
        "pending": [],
        "signoffs": {},
        "final_document": None,
        "outcome": None,
    }


def current_sections(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if state.get("phase") == PHASE_CLOSING:
        return {d: {"draft_content": s["draft_content"]} for d, s in (state.get("signoffs") or {}).items()}
    return state.get("sections") or {}


def detect(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    conflicts = detect_conflicts(
        current_sections(state), currency=state.get("currency"),
        monthly_volume=state.get("monthly_volume"), overrides=state.get("overrides"),
    )
    return {"conflicts": [c.model_dump() for c in conflicts]}


def route_after_detect(state: dict[str, Any]) -> str:
    if state.get("conflicts"):
        return NODE_ARBITRATE
    return NODE_CLOSE if state.get("phase") == PHASE_CLOSING else NODE_OPEN


def arbitrate_node(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    round_number = int(state.get("arbitration_round") or 0) + 1
    result = arbitrate(state.get("conflicts") or [], round_number=round_number)
    deps.reporter.arbitration(state.get("ticket_id"), result.decisions, result.rejected)
    overrides = {d: dict(v) for d, v in (state.get("overrides") or {}).items()}
    for department_id, values in result.overrides.items():
        overrides.setdefault(department_id, {}).update(values)
    return {
        "arbitration_round": round_number,
        "arbitrations": result.decisions,
        "forced": result.forced,
        "overrides": overrides,
        "rejected": {**(state.get("rejected") or {}), **result.rejected},
        "blocked": result.blocked,
    }


def route_after_arbitrate(state: dict[str, Any]) -> str:
    return NODE_REJECT if state.get("rejected") or state.get("blocked") else NODE_OPEN


def _notes(decisions: list[dict[str, Any]], department_id: str) -> list[str]:
    return [
        f"{d['arbiter']} · {d['trigger']} (ronda {d['round']}): {d['detail']}"
        for d in decisions if department_id in d["departments"] and d["action"] == "request_changes"
    ]


def open_branches(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    if deps.branches is None:
        raise RuntimeError("open_branches necesita el servicio de ramas")
    forced = state.get("forced") or {}
    arbitrations = state.get("arbitrations") or []
    signoffs = dict(state.get("signoffs") or {})
    inputs: dict[str, dict[str, Any]] = {}
    if state.get("phase") == PHASE_CLOSING:
        # Reabrir solo las secciones ofensoras: las demás conservan su aprobación.
        for department_id, changes in forced.items():
            signoffs.pop(department_id, None)
            inputs[department_id] = {"forced": changes, "arbitration_notes": _notes(arbitrations, department_id),
                                     "decision": None, "signoff": None, "outcome": None}
    else:
        contexts = {c.department_id: c for c in drafting_handoff.drafting_inputs(state["handoff"])}
        for department_id in state["departments"]:
            section = state["sections"][department_id]
            inputs[department_id] = {
                "ticket_id": state.get("ticket_id"),
                "department_id": department_id,
                "department_name": section["department_name"],
                "responsible": section["responsible"],
                "client_name": (state.get("client") or {}).get("name"),
                "currency": state.get("currency"),
                "context": contexts[department_id].model_dump(mode="json"),
                "section": {k: section[k] for k in ("draft_content", "draft_status", "iterations", "draft_source",
                                                    "evaluation_result", "provisional")},
                "forced": forced.get(department_id, []),
                "arbitration_notes": _notes(arbitrations, department_id),
                "round": 0,
                "max_rounds": config.MAX_APPROVAL_ROUNDS,
                "approval_requested_at": None,
                "decision": None,
                "signoff": None,
                "outcome": None,
            }
    results = deps.branches.start_many(state.get("ticket_id"), inputs)
    pending = [d for d in intake_config.DEPARTMENT_ORDER if d in results and results[d].get("waiting")]
    for department_id, result in results.items():
        if result.get("signoff"):
            signoffs[department_id] = result["signoff"]
    pending = sorted(set(pending) | set(d for d in state.get("pending") or [] if d not in results),
                     key=intake_config.DEPARTMENT_ORDER.index)
    deps.reporter.awaiting(state.get("ticket_id"), pending)
    return {"pending": pending, "signoffs": signoffs, "forced": {}, "phase": PHASE_OPENING}


def await_signoffs(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    pending = list(state.get("pending") or [])
    if not pending:
        return {"phase": PHASE_CLOSING}
    raw = interrupt({"ticket_id": state.get("ticket_id"), "waiting_for": pending})
    try:
        event = SignoffEvent.model_validate(raw)
    except (ValidationError, TypeError):
        return {}
    if event.department_id not in pending:
        return {}  # aviso repetido o de una rama que no se esperaba: no cambia nada
    remaining = [d for d in pending if d != event.department_id]
    update: dict[str, Any] = {
        "signoffs": {**(state.get("signoffs") or {}), event.department_id: event.model_dump()},
        "pending": remaining,
    }
    if not remaining:
        update["phase"] = PHASE_CLOSING
    return update


def route_after_await(state: dict[str, Any]) -> str:
    signoffs = state.get("signoffs") or {}
    if any(s["approval_status"] == config.APPROVAL_REJECTED for s in signoffs.values()):
        return NODE_REJECT
    if state.get("pending"):
        return NODE_AWAIT
    return NODE_DETECT


def close_document(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    deps.reporter.closing(state.get("ticket_id"))
    document = build_final_document(
        ticket_id=state.get("ticket_id"), rfp_id=state.get("rfp_id"), client=state.get("client") or {},
        currency=state.get("currency"), signoffs=state.get("signoffs") or {},
        arbitrations=state.get("arbitrations") or [], created_at=state.get("created_at"),
    )
    deps.reporter.final_document(state.get("ticket_id"), document)
    return {"final_document": document, "outcome": config.STATUS_DONE}


def reject_ticket(state: dict[str, Any], deps: Deps) -> dict[str, Any]:
    rejected = dict(state.get("rejected") or {})
    for department_id, signoff in (state.get("signoffs") or {}).items():
        if signoff["approval_status"] == config.APPROVAL_REJECTED:
            rejected[department_id] = f"{signoff['approver']} ({signoff['reason']}): {signoff['comment']}".strip()
    deps.reporter.rejected(state.get("ticket_id"), rejected, list(state.get("blocked") or []))
    return {"rejected": rejected, "outcome": config.APPROVAL_REJECTED}
