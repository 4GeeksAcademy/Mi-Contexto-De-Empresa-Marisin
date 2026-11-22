"""Nodos y routers del agente de soporte. Cada nodo tiene una sola responsabilidad.

Los nodos **no reimplementan** el RAG ni las tools: llaman a
`data/pipelines/rag.py`, `services/agent/routing.py` y `services/agent/tools.py`
a través del módulo (`rag_pipeline.retrieve`, `agent_tools.lookup_tickets`, …)
para que los tests puedan sustituirlas. Ningún nodo llama a
`rag_pipeline.query()`: eso volvería a recuperar y escondería la separación
recuperación → generación que el grafo hace explícita.

Cada nodo devuelve solo las claves del estado que cambia.

Memoria (Hito 8 · Parte 1): `receive_question` mira si la conversación tiene una
propuesta pendiente; si la hay, `resolve_memory_decision` clasifica el mensaje
contra ella **antes** de enrutar. `compose_answer` añade los hechos aprobados que
tocan la pregunta y `propose_memory` deja pendiente la `memory_proposal` del
modelo y añade la pregunta al final de la respuesta. La memoria solo se lee y
escribe con `services/agent/memory/store.py` y es *best-effort*: si Redis no
responde, el agente contesta igual, sin memoria.

Harness (Hito 8 · Parte 2): `receive_question` pasa el mensaje por la guardia de
entrada determinista (inyección, autorización por sesión, datos sensibles, uso
personal, mezcla de políticas, small talk); lo que se bloquea va a
`guardrail_block` y nunca llega al LLM ni a las tools. `route_question` añade la
segunda capa (alcance semántico del enrutador). El small talk y la trivia los
contesta `redirect_out_of_scope` con una plantilla de rechazo, sin LLM. `generate_answer` usa el prompt
seguro de CX con los documentos aislados y `compose_answer` pasa la respuesta
final por la guardia de salida. Ver `services/agent/harness/`.
"""

import logging
from typing import Literal

from data.pipelines import rag as rag_pipeline

from . import answers
from . import routing as agent_routing
from . import tools as agent_tools
from .harness import authorization as guard_authorization
from .harness import events as guard_events
from .harness import generation as agent_generation
from .harness import input_guard, isolation, output_guard, responses
from .memory import decision as memory_decision
from .memory import flow as memory_flow
from .memory import store as memory_store
from .memory.models import Actor, MemoryDraft, PendingProposal
from .state import AgentState

logger = logging.getLogger("agent.nodes")

INVALID_QUESTION_ANSWER = (
    "La pregunta está vacía. Escribe qué necesitas saber sobre las políticas de TrackFlow "
    "(entregas, devoluciones, transportistas o almacenaje), un ticket o el stock de un producto."
)
NO_CONTEXT_ANSWER = (
    "No tengo información sobre eso en la base de conocimiento de TrackFlow, así que prefiero "
    "no darte una respuesta que no pueda respaldar. Te recomiendo consultarlo con el responsable "
    "del área.\n"
    "Fuente: ninguna (sin información en la base de conocimiento)"
)
TOOL_RESULT_KEYS = ("ticket_result", "inventory_result")


# --------------------------------------------------------------------------- #
# Recepción y enrutamiento
# --------------------------------------------------------------------------- #
def _actor(state: AgentState) -> Actor | None:
    return Actor.model_validate(state["actor"]) if state.get("actor") else None


def memory_enabled(state: AgentState) -> bool:
    """La memoria solo actúa en corridas con conversación y usuario (las de la API)."""
    return bool(state.get("conversation_id")) and bool(state.get("actor"))


def _user_id(state: AgentState) -> int | None:
    actor = _actor(state)
    return actor.user_id if actor else None


def receive_question(state: AgentState) -> AgentState:
    """Recibe la pregunta, la pasa por la guardia de entrada y mira si hay una propuesta de memoria pendiente."""
    question = (state.get("question") or "").strip()
    update: AgentState = {"question": question, "status": "received" if question else "invalid"}
    if not question:
        return update
    verdict = input_guard.check_input(question, user_id=_user_id(state))
    update["guardrail"] = verdict.model_dump(mode="json", exclude_defaults=True) | {"category": verdict.category, "action": verdict.action}
    if verdict.action != "allow":
        guard_events.record(guard="input", category=verdict.category, failure_type=verdict.failure_type,
                            action=verdict.action, rules=verdict.rules)
    if verdict.country_lock:
        update["country_lock"] = verdict.country_lock
    if memory_enabled(state):
        try:
            pending, expired = memory_flow.check_pending(
                memory_store.get_store(), state["conversation_id"], _actor(state)
            )
        except Exception as exc:  # Redis caído: el turno sigue sin memoria
            logger.warning("Memoria no disponible al leer la propuesta pendiente: %s", exc)
            pending, expired = None, None
        if pending is not None:
            update["pending_memory"] = pending.model_dump(mode="json")
        if expired is not None:
            update["memory_decision"] = expired.model_dump(mode="json", exclude_none=True)
    return update


def resolve_memory_decision(state: AgentState) -> AgentState:
    """Clasifica el mensaje contra la propuesta pendiente y la resuelve. Solo aprobar/editar escribe."""
    pending = PendingProposal.model_validate(state["pending_memory"])
    message = state["question"]
    classification = memory_decision.classify_decision(pending, message)
    try:
        result = memory_flow.apply_decision(
            memory_store.get_store(), pending, classification,
            message=message, actor=_actor(state), run_id=state.get("run_id"),
        )
        decision = result.model_dump(mode="json", exclude_none=True)
    except Exception as exc:
        logger.warning("Memoria no disponible al resolver la propuesta %s: %s", pending.proposal_id, exc)
        decision = {
            "proposal_id": pending.proposal_id, "outcome": "memory_unavailable", "slot_id": pending.slot_id,
            "proposed_fact": pending.draft.fact, "label": classification.label,
            "message": "No he podido acceder a la memoria del agente, así que no se ha guardado nada.",
        }
    return {
        "memory_decision": decision,
        "question": classification.remaining_question.strip(),
        "status": "memory_resolved",
    }


def reject_invalid_question(state: AgentState) -> AgentState:
    """Salida clara para una pregunta vacía: no se recupera nada."""
    return {"answer": INVALID_QUESTION_ANSWER, "status": "invalid"}


def route_question(state: AgentState) -> AgentState:
    """Decide qué fuentes necesita la pregunta (LLM con reglas de respaldo) y su alcance (2.ª capa)."""
    decision = agent_routing.decide_route(state["question"])
    route = {**decision.model_dump(mode="json", exclude_none=True), "sources": decision.sources}
    update: AgentState = {"route": route, "status": "routed"}
    if decision.scope != "domain":
        category = SCOPE_CATEGORY[decision.scope]
        action = "block" if decision.scope in agent_routing.BLOCKING_SCOPES else "redirect"
        failure = "security" if decision.scope == "injection" else "content"
        guard_events.record(guard="router_scope", category=category, failure_type=failure, action=action,
                            rules=[f"llm_scope:{decision.scope}"])
        if action == "block" or (state.get("guardrail") or {}).get("action") == "allow":
            update["guardrail"] = {"category": category, "action": action, "failure_type": failure,
                                   "rules": [f"llm_scope:{decision.scope}"]}
    return update


# Alcance del enrutador → categoría de la guardia de entrada.
SCOPE_CATEGORY = {
    "general_logistics": "general_logistics", "casual": "casual", "personal": "personal_task",
    "sensitive": "sensitive_request", "injection": "injection",
}


# --------------------------------------------------------------------------- #
# Harness: bloqueo, small talk y envíos de la sesión
# --------------------------------------------------------------------------- #
def guardrail_block(state: AgentState) -> AgentState:
    """Rechazo firme con plantilla (sin LLM, sin tools). Descarta una propuesta de memoria pendiente."""
    guard = state.get("guardrail") or {}
    category = guard.get("category", "personal_task")
    strikes = 0
    if category == "injection" and state.get("conversation_id"):
        try:
            strikes = guard_events.get_log().strikes(state["conversation_id"])
        except Exception as exc:
            logger.warning("No se pudo contar los intentos de la conversación: %s", exc)
        if strikes >= 3:
            guard_events.record(guard="input", category="repeated_injection", failure_type="security",
                                action="block", rules=[f"strikes:{strikes}"])
    update: AgentState = {
        "answer": responses.block_message(category, denied_orders=guard.get("denied_orders"), strikes=strikes),
        "status": "blocked",
    }
    if state.get("pending_memory"):
        # El mensaje no responde a la propuesta: se descarta (nunca se aprueba por un mensaje bloqueado).
        pending = PendingProposal.model_validate(state["pending_memory"])
        classification = memory_decision.DecisionClassification(
            label="unrelated", confidence=1.0, decided_by="rules", reason=f"Mensaje bloqueado por el harness ({category})")
        try:
            result = memory_flow.apply_decision(memory_store.get_store(), pending, classification,
                                                message=state["question"], actor=_actor(state), run_id=state.get("run_id"))
            update["memory_decision"] = result.model_dump(mode="json", exclude_none=True)
        except Exception as exc:
            logger.warning("No se pudo descartar la propuesta pendiente: %s", exc)
    return update


def redirect_out_of_scope(state: AgentState) -> AgentState:
    """Small talk y trivia: **solo rechazo con plantilla, sin LLM** (Ticket #SEC-114, C02).

    No se contesta el dato fuera de dominio («París», la hora en Tokio): un saludo o un
    agradecimiento reciben una cortesía breve y todo lo demás, el rechazo. La
    reconducción a TrackFlow la añade `compose_answer`.
    """
    rules = (state.get("guardrail") or {}).get("rules") or []
    return {"out_of_scope_reply": responses.out_of_scope_reply(rules), "status": "redirected"}


def lookup_shipment(state: AgentState) -> AgentState:
    """Envíos de la sesión (ya autorizados por la guardia de entrada). No consulta nada ajeno."""
    shipments = (state.get("guardrail") or {}).get("authorized_orders") or []
    return {"shipment_result": shipments, "status": "tool_done"}


# --------------------------------------------------------------------------- #
# Tools (datos en vivo, solo lectura)
# --------------------------------------------------------------------------- #
def lookup_ticket(state: AgentState) -> AgentState:
    """Tool 1: consulta el gestor de incidentes (GET, timeout de 4 s)."""
    query = agent_tools.TicketQuery.model_validate(state["route"]["ticket"])
    result = agent_tools.lookup_tickets(query)
    data = isolation.sanitize_tool_result(result.model_dump(mode="json"), source="tool:incidents")
    return {"ticket_result": data, "status": "tool_done"}


def lookup_inventory(state: AgentState) -> AgentState:
    """Tool 2: consulta el gestor de inventario (GET, timeout de 4 s)."""
    query = agent_tools.InventoryQuery.model_validate(state["route"]["inventory"])
    result = agent_tools.lookup_inventory(query)
    data = isolation.sanitize_tool_result(result.model_dump(mode="json"), source="tool:inventory")
    return {"inventory_result": data, "status": "tool_done"}


def tool_fallback(state: AgentState) -> AgentState:
    """Ruta de recuperación: la tool falló o el recurso no existe. Responde con honestidad."""
    update: AgentState = {"status": "tool_fallback"}
    for key in TOOL_RESULT_KEYS:
        result = state.get(key)
        if result and result["status"] != "ok" and not result.get("fallback_message"):
            update[key] = {**result, "fallback_message": answers.fallback_message(result)}
    return update


# --------------------------------------------------------------------------- #
# RAG
# --------------------------------------------------------------------------- #
def _other_country_only(chunk: dict, country: str) -> bool:
    """El chunk habla solo del otro país (no del país fijado)."""
    mentioned = guard_authorization.countries_mentioned(f"{chunk.get('section', '')} {chunk.get('text', '')}")
    return bool(mentioned) and country not in mentioned


def retrieve_context(state: AgentState) -> AgentState:
    """Ejecuta `retrieve()` del RAG; ya filtra por `min_score` y puede devolver [].

    Con `country_lock` (mezcla de políticas, BRIEFING caso 4) se busca la política del
    país real y se descartan los chunks que solo hablan del otro país.
    """
    country = state.get("country_lock")
    query = state["question"]
    if (state.get("guardrail") or {}).get("category") == "general_logistics":
        query = input_guard.trackflow_query(query)  # cómo lo aplica TrackFlow, no la definición general
    if country:
        query = f"{query} ({guard_authorization.COUNTRY_NAMES[country]})"
    context = rag_pipeline.retrieve(query)
    if country:
        context = [chunk for chunk in context if not _other_country_only(chunk, country)]
    return {"context": context, "status": "retrieved"}


def generate_answer(state: AgentState) -> AgentState:
    """Genera la parte RAG con el prompt seguro de CX y los documentos aislados (`harness/generation.py`)."""
    question = state["question"]
    context = state.get("context") or []
    extra = {"country_lock": state["country_lock"]} if state.get("country_lock") else {}
    answer = output_guard.check_rag_answer(agent_generation.generate_answer(question, context, **extra))
    unsupported = rag_pipeline.unsupported_figures(answer, context, question)
    if unsupported:
        logger.warning("Respuesta con cifras que no están en el contexto: %s", unsupported)
    return {"rag_answer": answer, "status": "answered"}


def answer_without_context(state: AgentState) -> AgentState:
    """Salida honesta cuando ningún chunk supera el umbral. No llama al LLM."""
    return {"rag_answer": NO_CONTEXT_ANSWER, "status": "no_context"}


# --------------------------------------------------------------------------- #
# Composición
# --------------------------------------------------------------------------- #
def _recall(state: AgentState) -> list[dict]:
    if not memory_enabled(state) or not state.get("question"):
        return []
    try:
        return memory_flow.recall_notes(memory_store.get_store(), state["question"])
    except Exception as exc:
        logger.warning("Memoria no disponible al recordar: %s", exc)
        return []


def compose_answer(state: AgentState) -> AgentState:
    """Une las partes: decisión de memoria, tools (con plantilla), RAG y notas recordadas."""
    results = [state[key] for key in TOOL_RESULT_KEYS if state.get(key)]
    decision = state.get("memory_decision")
    guard = state.get("guardrail") or {}
    sections = [decision["message"]] if decision else []
    if guard.get("category") == "policy_override" and state.get("country_lock"):
        sections.append(responses.policy_override_prefix(guard.get("requested_country"), state["country_lock"]))
    if state.get("shipment_result"):
        sections.append(guard_authorization.shipment_section(state["shipment_result"]))
    if state.get("out_of_scope_reply"):
        sections.append(state["out_of_scope_reply"])
    sections.extend(answers.tool_section(result) for result in results)
    if state.get("rag_answer"):
        sections.append(state["rag_answer"])
    notes = _recall(state)
    if notes:
        # Plantilla, no LLM: la nota aparece tal como se aprobó y separada de la base documental.
        sections.append(memory_flow.notes_section(notes))
    if guard.get("category") == "casual":
        sections.append(responses.REDIRECT)  # la reconducción la pone el harness, no el modelo
    elif guard.get("category") == "general_logistics":
        sections.append(responses.GENERAL_LOGISTICS_REDIRECT)

    rag_answered = bool(state.get("context")) and bool(state.get("rag_answer"))
    if state.get("out_of_scope_reply"):
        status = "redirected"
    elif rag_answered or state.get("shipment_result") or any(result["status"] == "ok" for result in results):
        status = "answered"
    elif results:
        status = "tool_fallback"
    elif decision and not state.get("rag_answer"):
        status = "memory_resolved"  # el mensaje solo respondía a la propuesta
    else:
        status = "no_context"
    authorized = [item["reference"] for item in state.get("shipment_result") or []]
    verdict = output_guard.check_output("\n\n".join(sections), authorized_refs=authorized)
    update: AgentState = {"answer": verdict.answer, "status": "blocked" if verdict.blocked else status}
    if notes:
        update["memory_notes"] = notes
    return update


def propose_memory(state: AgentState) -> AgentState:
    """Auto-evaluación: deja PENDIENTE la propuesta del modelo y la pregunta al usuario. No escribe memoria."""
    draft = MemoryDraft.model_validate(state["route"]["memory_proposal"])
    try:
        result = memory_flow.submit_proposal(
            memory_store.get_store(), draft,
            conversation_id=state.get("conversation_id"), actor=_actor(state),
            message=state.get("question") or "", run_id=state.get("run_id"),
        )
    except Exception as exc:
        logger.warning("Memoria no disponible al proponer: %s", exc)
        result = memory_flow.ProposalResult(status="skipped", reasons=["memory_unavailable"])
    update: AgentState = {"memory_proposal": result.model_dump(mode="json", exclude_none=True)}
    if result.question_text:
        update["answer"] = f"{state.get('answer') or ''}\n\n{result.question_text}".strip()
    return update


# --------------------------------------------------------------------------- #
# Routers (condiciones de salida de las aristas condicionales)
# --------------------------------------------------------------------------- #
def route_after_receive(
    state: AgentState,
) -> Literal["valid", "empty", "memory_decision", "blocked", "casual", "shipment"]:
    if not state.get("question"):
        return "empty"
    guard = state.get("guardrail") or {}
    if guard.get("action") == "block":
        return "blocked"
    if state.get("pending_memory"):
        return "memory_decision"
    if guard.get("authorized_orders") and guard.get("category") == "domain":
        return "shipment"
    if guard.get("category") == "casual":
        return "casual"  # rechazo con plantilla + reconducción, sin LLM
    return "valid"  # la logística general va al RAG: solo cómo lo aplica TrackFlow


def route_after_route(state: AgentState) -> Literal["ticket", "inventory", "rag", "compose", "blocked", "casual"]:
    """Segunda capa: si el enrutador LLM detecta un alcance bloqueado o small talk, no se consultan fuentes."""
    guard = state.get("guardrail") or {}
    if guard.get("action") == "block":
        return "blocked"
    if guard.get("category") == "casual":
        return "casual"
    return next_source(state)


def route_after_memory_decision(state: AgentState) -> Literal["continue", "compose"]:
    """Si el mensaje traía otra consulta además de la decisión, se enruta con normalidad."""
    return "continue" if state.get("question") else "compose"


def route_after_compose(state: AgentState) -> Literal["propose", "end"]:
    route = state.get("route") or {}
    return "propose" if route.get("memory_proposal") and memory_enabled(state) else "end"


def next_source(state: AgentState) -> Literal["ticket", "inventory", "rag", "compose"]:
    """Siguiente fuente pendiente según la decisión del enrutador: tools → RAG → composición."""
    route = state.get("route") or {}
    if route.get("ticket") is not None and "ticket_result" not in state:
        return "ticket"
    if route.get("inventory") is not None and "inventory_result" not in state:
        return "inventory"
    if route.get("needs_rag") and "context" not in state:
        return "rag"
    return "compose"


def route_after_tool(state: AgentState) -> Literal["fallback", "inventory", "rag", "compose"]:
    """Tras una tool: si falló y aún no se ha respondido con honestidad, va a `tool_fallback`."""
    for key in TOOL_RESULT_KEYS:
        result = state.get(key)
        if result and result["status"] != "ok" and not result.get("fallback_message"):
            return "fallback"
    return next_source(state)


def route_after_retrieve(state: AgentState) -> Literal["with_context", "without_context"]:
    return "with_context" if state.get("context") else "without_context"
