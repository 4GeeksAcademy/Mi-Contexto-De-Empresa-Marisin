"""Ciclos completos de memoria a través del grafo real (sin Qdrant, LLM, MCP ni Redis).

El LLM enrutador y el clasificador de la decisión se sustituyen por dobles que
devuelven JSON, pero el JSON pasa por los parsers y las guardas reales.

* Ciclo aprobado: propuesta → "sí" → consolidación → la nota aparece en otra conversación.
* Ciclo rechazado: propuesta → "no" → la memoria no cambia y no aparece después.
* Cambio de tema, aprobación + otra pregunta en el mismo mensaje, LLM caído y Redis caído.

    python -m pytest tests/pipelines/test_agent_memory_graph.py
"""

import json

import pytest

from data.pipelines import rag as rag_pipeline
from services.agent import graph as agent_graph
from services.agent.harness import generation as agent_generation
from services.agent import mcp_client, routing, runner
from services.agent.memory import decision as memory_decision
from services.agent.memory import store as memory_store
from services.agent.memory.backend import MemoryUnavailable

AGENT = {"id": 7, "role": "user", "email": "agente@trackflow.test"}
CONTEXT = [{"source_document": "returns-policy", "section": "Devoluciones", "text": "Ventana estándar: 30 días."}]
RAG_ANSWER = "La ventana estándar es de 30 días.\nFuente: Política de Devoluciones"
TICKET = {
    "id": "3", "title": "Caja aplastada", "description": "d", "category": "DAMAGE", "status": "in_progress",
    "origin": "customer", "branch": "Zaragoza",
    "created_at": "2026-11-10T09:00:00+00:00", "updated_at": "2026-11-15T12:00:00+00:00",
}

SEUR_MESSAGE = "En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado."
SEUR_FACT = "SEUR ya no cubre la zona rural de Zaragoza: usar el carrier local desde el mes pasado."
B2B_MESSAGE = "El cliente de cosméticos siempre quiere su reporte mensual con el desglose de devoluciones primero."
B2B_FACT = "El cliente de cosméticos quiere el reporte mensual con el desglose de devoluciones primero."

# Lo que "devuelve el LLM" enrutador para cada mensaje (el resto: LLM caído → reglas, sin propuesta).
ROUTER_OUTPUTS = {
    SEUR_MESSAGE: {"needs_rag": True, "reason": "corrección de cobertura", "memory_proposal": {
        "category": "carrier_rule", "fact": SEUR_FACT, "carrier": "SEUR", "country": "ES",
        "zone": "zona rural de Zaragoza", "reason": "corrige una regla de asignación"}},
    B2B_MESSAGE: {"needs_rag": True, "reason": "preferencia de reporte", "memory_proposal": {
        "category": "b2b_report_preference", "fact": B2B_FACT, "client": "cosméticos",
        "reason": "preferencia recurrente de un cliente B2B"}},
    "El cliente de Zaragoza vive en Calle Mayor 12 y SEUR no llega.": {"needs_rag": True, "memory_proposal": {
        "category": "carrier_rule", "fact": "SEUR no llega a Calle Mayor 12 de Zaragoza.", "carrier": "SEUR",
        "country": "ES"}},
}
DECISIONS = {
    "sí, recuérdalo": {"label": "approve", "confidence": 0.97},
    "no, no hace falta": {"label": "reject", "confidence": 0.96},
    "¿En qué estado está el ticket 3?": {"label": "unrelated", "confidence": 0.9,
                                          "remaining_question": "¿En qué estado está el ticket 3?"},
    "Sí, guárdalo. Y ¿cuál es la ventana de devolución estándar?": {
        "label": "approve", "confidence": 0.95, "remaining_question": "¿cuál es la ventana de devolución estándar?"},
    "bueno, ya veremos": {"label": "unclear", "confidence": 0.3},
}


@pytest.fixture
def fakes(monkeypatch):
    calls = {"router": [], "decision": []}

    def fake_router(question):
        calls["router"].append(question)
        if question not in ROUTER_OUTPUTS:
            raise RuntimeError("sin LLM en los tests")
        return routing.parse_llm_decision(json.dumps(ROUTER_OUTPUTS[question], ensure_ascii=False), question)

    def fake_decision(pending, message):
        calls["decision"].append(message)
        if message not in DECISIONS:
            raise RuntimeError("sin LLM en los tests")
        return memory_decision.parse_llm_decision(json.dumps(DECISIONS[message], ensure_ascii=False), message, pending)

    def fake_mcp(tool_name, arguments):
        if tool_name == "incidents_get" and arguments["incident_id"] == 3:
            return TICKET
        raise mcp_client.McpCallError("NOT_FOUND", "El recurso no existe en TrackFlow.", 404)

    monkeypatch.setattr(rag_pipeline, "retrieve", lambda q: list(CONTEXT) if "devoluci" in q.lower() else [])
    monkeypatch.setattr(agent_generation, "generate_answer", lambda q, c: RAG_ANSWER)
    monkeypatch.setattr(rag_pipeline, "query", lambda *_: pytest.fail("ningún nodo debe llamar a query()"))
    monkeypatch.setattr(mcp_client, "call_tool", fake_mcp)
    monkeypatch.setattr(routing, "classify_with_llm", fake_router)
    monkeypatch.setattr(memory_decision, "classify_with_llm", fake_decision)
    return calls


@pytest.fixture
def ask(fakes, tmp_path):
    graph = agent_graph.compile_graph()

    def _ask(question, conversation_id=None, user=AGENT):
        result = runner.run_agent(question, conversation_id=conversation_id, user=user, graph=graph,
                                  trace_directory=tmp_path)
        trace = json.loads(result.trace_path.read_text(encoding="utf-8"))
        return result, trace

    return _ask


def memory_snapshot():
    return [slot.model_dump() for slot in memory_store.get_store().list_slots()]


def audit_events():
    return [entry["event"] for entry in memory_store.get_store().audit_log()]


# --------------------------------------------------------------------------- #
# Ciclo 1 — aprobado y reflejado en una interacción futura
# --------------------------------------------------------------------------- #
def test_approved_cycle_is_consolidated_and_used_in_a_later_conversation(ask):
    first, trace = ask(SEUR_MESSAGE)
    conversation = first.conversation_id

    assert trace["path"][-2:] == ["compose_answer", "propose_memory"]
    assert "¿Quieres que recuerde esto para la próxima vez?" in first.answer
    assert first.memory["proposal"]["status"] == "proposed"
    assert memory_snapshot() == []  # proponer no escribe

    second, trace = ask("sí, recuérdalo", conversation)
    assert trace["path"] == ["receive_question", "resolve_memory_decision", "compose_answer"]
    assert second.status == "memory_resolved"
    assert second.memory["decision"]["outcome"] == "approved"
    assert second.answer.startswith("Guardado en la memoria del agente")
    assert [fact["fact"] for slot in memory_snapshot() for fact in slot["facts"]] == [SEUR_FACT]

    later, trace = ask("¿Qué carrier uso para un envío a la zona rural de Zaragoza?")  # otra conversación
    assert later.conversation_id != conversation
    assert SEUR_FACT in later.answer
    assert "Fuente: memoria del agente" in later.answer
    assert len(later.memory["notes"]) == 1
    assert audit_events() == ["proposed", "approved"]


# --------------------------------------------------------------------------- #
# Ciclo 2 — rechazado: la memoria no cambia
# --------------------------------------------------------------------------- #
def test_rejected_cycle_leaves_memory_unchanged(ask):
    before = memory_snapshot()
    first, _ = ask(B2B_MESSAGE)
    assert first.memory["proposal"]["status"] == "proposed"

    second, trace = ask("no, no hace falta", first.conversation_id)
    assert trace["path"] == ["receive_question", "resolve_memory_decision", "compose_answer"]
    assert second.memory["decision"]["outcome"] == "rejected"
    assert "no lo guardo" in second.answer
    assert memory_snapshot() == before

    later, _ = ask("Prepara el reporte del cliente de cosméticos")
    assert B2B_FACT not in later.answer
    assert "notes" not in later.memory
    assert audit_events() == ["proposed", "rejected"]


# --------------------------------------------------------------------------- #
# Ambigüedad y cambio de tema: descarte por defecto
# --------------------------------------------------------------------------- #
def test_topic_change_discards_the_proposal_and_answers_the_new_question(ask):
    staff = {**AGENT, "role": "manager"}  # la tool de incidencias es solo para el personal (D10)
    first, _ = ask(SEUR_MESSAGE, user=staff)
    second, trace = ask("¿En qué estado está el ticket 3?", first.conversation_id, user=staff)

    assert trace["path"] == ["receive_question", "resolve_memory_decision", "route_question", "lookup_ticket", "compose_answer"]
    assert second.memory["decision"]["outcome"] == "discarded_topic_change"
    assert "El ticket 3 «Caja aplastada» está en curso" in second.answer
    assert memory_snapshot() == []


def test_ambiguous_answer_is_never_an_approval(ask):
    first, _ = ask(SEUR_MESSAGE)
    second, _ = ask("bueno, ya veremos", first.conversation_id)

    assert second.memory["decision"]["outcome"] == "discarded_ambiguous"
    assert memory_snapshot() == []
    assert memory_store.get_store().get_pending(first.conversation_id) is None


def test_approval_and_a_new_question_in_the_same_message(ask):
    first, _ = ask(SEUR_MESSAGE)
    second, trace = ask("Sí, guárdalo. Y ¿cuál es la ventana de devolución estándar?", first.conversation_id)

    assert trace["path"] == ["receive_question", "resolve_memory_decision", "route_question", "retrieve",
                             "generate_answer", "compose_answer"]
    assert second.status == "answered"
    assert second.answer.startswith("Guardado en la memoria del agente")
    assert RAG_ANSWER in second.answer
    assert len(memory_snapshot()) == 1


def test_without_the_llm_a_compound_answer_is_discarded_but_still_answered(ask, fakes, monkeypatch):
    first, _ = ask(SEUR_MESSAGE)
    second, _ = ask("sí, y ¿cuál es la ventana de devolución estándar?", first.conversation_id)  # sin LLM (no está en DECISIONS)

    assert second.memory["decision"]["outcome"] == "discarded_ambiguous"
    assert RAG_ANSWER in second.answer
    assert memory_snapshot() == []


def test_expired_proposal_is_not_applied(ask, monkeypatch):
    first, _ = ask(SEUR_MESSAGE)
    store = memory_store.get_store()
    pending = store.get_pending(first.conversation_id)
    store.clear_pending(first.conversation_id)
    store.save_pending(pending.model_copy(update={"expires_at": "2000-01-01T00:00:00+00:00"}))

    second, trace = ask("sí, recuérdalo", first.conversation_id)

    assert "resolve_memory_decision" not in trace["path"]
    assert second.memory["decision"]["outcome"] == "expired"
    assert memory_snapshot() == []


# --------------------------------------------------------------------------- #
# Política, aislamiento y degradación
# --------------------------------------------------------------------------- #
def test_forbidden_proposal_is_never_shown_to_the_user(ask):
    result, trace = ask("El cliente de Zaragoza vive en Calle Mayor 12 y SEUR no llega.")

    assert result.memory["proposal"]["status"] == "blocked_by_policy"
    assert "¿Quieres que recuerde" not in result.answer
    assert "Calle Mayor" not in json.dumps(memory_store.get_store().audit_log(), ensure_ascii=False)


def test_without_a_user_the_memory_is_off_and_the_path_is_unchanged(ask):
    result, trace = ask(SEUR_MESSAGE, user=None)
    assert trace["path"] == ["receive_question", "route_question", "retrieve", "no_context", "compose_answer"]
    assert result.conversation_id is None
    assert audit_events() == []


def test_the_agent_still_answers_when_redis_is_down(ask, monkeypatch):
    class Down:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise MemoryUnavailable("Redis no responde")
            return fail

    monkeypatch.setattr(memory_store, "get_store", lambda: Down())
    result, trace = ask(SEUR_MESSAGE)
    assert result.status == "no_context"
    assert result.memory["proposal"]["reasons"] == ["memory_unavailable"]
