"""Grafos LangGraph de la Parte 3: `rfp_department_approval` (una rama) y `rfp_approval` (ticket).

    rfp_department_approval  (hilo rfp-{ticket_id}:{department_id}, uno por departamento activo)

        START → prepare_review ─forzado por el árbitro─→ revise_section ─┐
                     └──────────────────────────────→ request_approval ←┘
                                                           ↓
                                  ┌──────────────── human_approval ⏸ interrupt(ApprovalRequest)
                                  │   approve / reject ↓        └─ request_changes (quedan rondas) → revise_section
                                  └──────────────→ record_signoff → END

    rfp_approval  (hilo rfp-{ticket_id})

        START → load_drafts → detect_conflicts ─conflicto─→ arbitrate ─rechazo / bloqueo─→ reject_ticket → END
                                    │ sin conflicto            │ request_changes
                                    ↓                          ↓
                                open_branches ←────────────────┘   (arranca o reabre ramas en paralelo)
                                    ↓
                             await_signoffs ⏸ interrupt ⟲ (un SignoffEvent por rama terminada)
                                    ↓ todas aprobadas                └─ alguna rechazada → reject_ticket
                             detect_conflicts (sobre lo aprobado) → close_document → END

Cada rama tiene su propio hilo de checkpointer: interrumpir la de `warehouse` no
toca la de `lastmile`, que se puede aprobar, rechazar o reescribir mientras la
otra sigue en pausa. El grafo del ticket solo espera los sign-offs y no se
reanuda por una rama hasta que esta termina. `resume` = `Command(resume=…)`
sobre el mismo hilo: continúa en el nodo interrumpido, nunca desde START.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..llm import LLM
from . import config, nodes
from .reporter import ApprovalReporter, NullApprovalReporter
from .state import DepartmentApprovalState, TicketApprovalState
from .trace import TraceSink, traced

DEPARTMENT_INPUT_KEYS = {
    nodes.NODE_PREPARE: ("department_id", "round", "forced"),
    nodes.NODE_REVISE: ("department_id", "round", "forced", "decision"),
    nodes.NODE_REQUEST: ("department_id", "round"),
    nodes.NODE_HUMAN: ("department_id", "round", "approval_requested_at"),
    nodes.NODE_SIGNOFF: ("department_id", "decision", "round"),
}
TICKET_INPUT_KEYS = {
    nodes.NODE_LOAD: ("ticket_id", "rfp_id"),
    nodes.NODE_DETECT: ("phase", "currency", "monthly_volume", "overrides"),
    nodes.NODE_ARBITRATE: ("conflicts", "arbitration_round"),
    nodes.NODE_OPEN: ("phase", "departments", "forced"),
    nodes.NODE_AWAIT: ("pending",),
    nodes.NODE_CLOSE: ("signoffs",),
    nodes.NODE_REJECT: ("rejected", "blocked"),
}


def _department_thread(state: dict[str, Any]) -> str:
    return config.department_thread_id(state.get("ticket_id"), state.get("department_id"))


def _ticket_thread(state: dict[str, Any]) -> str:
    return config.ticket_thread_id(state.get("ticket_id"))


def _bind(fn, deps: nodes.Deps):
    def run(state):
        return fn(state, deps)

    run.__name__ = fn.__name__
    return run


def build_department_graph(
    *, llm: LLM | None = None, reporter: ApprovalReporter | None = None, sink: TraceSink | None = None,
    checkpointer=None,
):
    deps = nodes.Deps(llm=llm, reporter=reporter or NullApprovalReporter())
    agents = {
        nodes.NODE_PREPARE: "approval_coordinator",
        nodes.NODE_REVISE: lambda s: f"{s.get('department_id')}_generator + evaluadores (Parte 2)",
        nodes.NODE_REQUEST: "approval_coordinator",
        nodes.NODE_HUMAN: lambda s: f"humano: {s.get('responsible')}",
        nodes.NODE_SIGNOFF: "approval_coordinator",
    }
    functions = {
        nodes.NODE_PREPARE: nodes.prepare_review,
        nodes.NODE_REVISE: nodes.revise_section,
        nodes.NODE_REQUEST: nodes.request_approval,
        nodes.NODE_HUMAN: nodes.human_approval,
        nodes.NODE_SIGNOFF: nodes.record_signoff,
    }
    builder = StateGraph(DepartmentApprovalState)
    for name, fn in functions.items():
        builder.add_node(name, traced(agents[name], name, _bind(fn, deps), graph=config.DEPARTMENT_GRAPH_NAME,
                                      thread_id=_department_thread, sink=sink, input_keys=DEPARTMENT_INPUT_KEYS[name]))
    builder.add_edge(START, nodes.NODE_PREPARE)
    builder.add_conditional_edges(nodes.NODE_PREPARE, nodes.route_after_prepare,
                                  {n: n for n in (nodes.NODE_REVISE, nodes.NODE_REQUEST, nodes.NODE_SIGNOFF)})
    builder.add_edge(nodes.NODE_REVISE, nodes.NODE_REQUEST)
    builder.add_edge(nodes.NODE_REQUEST, nodes.NODE_HUMAN)
    builder.add_conditional_edges(nodes.NODE_HUMAN, nodes.route_after_human,
                                  {n: n for n in (nodes.NODE_HUMAN, nodes.NODE_REVISE, nodes.NODE_SIGNOFF)})
    builder.add_edge(nodes.NODE_SIGNOFF, END)
    return builder.compile(checkpointer=checkpointer, name=config.DEPARTMENT_GRAPH_NAME)


def build_ticket_graph(
    *, branches: nodes.Branches | None = None, reporter: ApprovalReporter | None = None,
    sink: TraceSink | None = None, checkpointer=None,
):
    deps = nodes.Deps(reporter=reporter or NullApprovalReporter(), branches=branches)
    agents = {
        nodes.NODE_LOAD: "approval_coordinator",
        nodes.NODE_DETECT: "conflict_detector",
        nodes.NODE_ARBITRATE: "arbiter (árbitro fijo, BRIEFING §7)",
        nodes.NODE_OPEN: "approval_coordinator",
        nodes.NODE_AWAIT: "signoff_gate",
        nodes.NODE_CLOSE: "ultimate_document_synthesizer",
        nodes.NODE_REJECT: "approval_coordinator",
    }
    functions = {
        nodes.NODE_LOAD: nodes.load_drafts,
        nodes.NODE_DETECT: nodes.detect,
        nodes.NODE_ARBITRATE: nodes.arbitrate_node,
        nodes.NODE_OPEN: nodes.open_branches,
        nodes.NODE_AWAIT: nodes.await_signoffs,
        nodes.NODE_CLOSE: nodes.close_document,
        nodes.NODE_REJECT: nodes.reject_ticket,
    }
    builder = StateGraph(TicketApprovalState)
    for name, fn in functions.items():
        builder.add_node(name, traced(agents[name], name, _bind(fn, deps), graph=config.GRAPH_NAME,
                                      thread_id=_ticket_thread, sink=sink, input_keys=TICKET_INPUT_KEYS[name]))
    builder.add_edge(START, nodes.NODE_LOAD)
    builder.add_edge(nodes.NODE_LOAD, nodes.NODE_DETECT)
    builder.add_conditional_edges(nodes.NODE_DETECT, nodes.route_after_detect,
                                  {n: n for n in (nodes.NODE_ARBITRATE, nodes.NODE_OPEN, nodes.NODE_CLOSE)})
    builder.add_conditional_edges(nodes.NODE_ARBITRATE, nodes.route_after_arbitrate,
                                  {n: n for n in (nodes.NODE_REJECT, nodes.NODE_OPEN)})
    builder.add_edge(nodes.NODE_OPEN, nodes.NODE_AWAIT)
    builder.add_conditional_edges(nodes.NODE_AWAIT, nodes.route_after_await,
                                  {n: n for n in (nodes.NODE_REJECT, nodes.NODE_AWAIT, nodes.NODE_DETECT)})
    builder.add_edge(nodes.NODE_CLOSE, END)
    builder.add_edge(nodes.NODE_REJECT, END)
    return builder.compile(checkpointer=checkpointer, name=config.GRAPH_NAME)
