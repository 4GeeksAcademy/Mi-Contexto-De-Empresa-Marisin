"""Pruebas del enrutador híbrido (LLM + guardas + reglas) y de las respuestas con plantilla.

    python -m pytest tests/pipelines/test_agent_routing.py
"""

from types import SimpleNamespace

import pytest

from data.pipelines import rag as rag_pipeline
from services.agent import answers, routing


# --------------------------------------------------------------------------- #
# Reglas
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "question, sources, ticket, inventory",
    [
        ("¿En qué estado está el ticket 482?", ["incidents"], {"ticket_id": 482}, None),
        ("What is the status of incident 7?", ["incidents"], {"ticket_id": 7}, None),
        ("¿Tenemos incidencias abiertas en Los Ángeles?", ["incidents"], {"status": "open", "branch": "Los Angeles"}, None),
        ("Muéstrame los tickets de paquetes perdidos", ["incidents"], {"category": "LOST_PARCEL"}, None),
        ("Tengo un ticket #12, ¿cuál es el SLA de entrega?", ["incidents", "rag"], {"ticket_id": 12}, None),
        ("¿Tenemos stock del SKU TF-BOX-001?", ["inventory"], None, {"sku": "TF-BOX-001"}),
        ("¿Hay stock de cajas de cartón?", ["inventory"], None, {"product_name": "cajas de carton"}),
        ("¿Cuál es la ventana de devolución estándar?", ["rag"], None, None),
        ("¿Cuánto cuesta el almacenamiento por metro cúbico al mes en Los Ángeles?", ["rag"], None, None),
        ("¿Qué hago si un cliente abre una incidencia por un paquete dañado?", ["rag"], None, None),
        ("¿Cuál es la capital de Francia?", ["rag"], None, None),
    ],
)
def test_rules_route_by_question_content(question, sources, ticket, inventory):
    decision = routing.classify_with_rules(question)
    assert decision.sources == sources
    assert (decision.ticket.model_dump(mode="json", exclude_none=True) if decision.ticket else None) == ticket
    assert (decision.inventory.model_dump(mode="json", exclude_none=True) if decision.inventory else None) == inventory
    assert decision.decided_by == "rules"


# --------------------------------------------------------------------------- #
# Decisión del LLM: contrato y guardas de anclaje
# --------------------------------------------------------------------------- #
def test_llm_json_is_parsed_into_the_typed_contract():
    text = '```json\n{"needs_rag": false, "ticket": {"ticket_id": 482, "status": null}, "inventory": null, "reason": "estado"}\n```'
    decision = routing.parse_llm_decision(text, "¿En qué estado está el ticket 482?")
    assert decision.decided_by == "llm"
    assert decision.sources == ["incidents"]
    assert decision.ticket.ticket_id == 482


@pytest.mark.parametrize(
    "text, question, why",
    [
        ('{"needs_rag": false, "ticket": {"ticket_id": 17}}', "¿Estado del ticket 482?", "no aparece"),
        ('{"needs_rag": false, "inventory": {"sku": "ABC-1"}}', "¿Hay stock de tornillos?", "no aparece"),
        ('{"needs_rag": false, "inventory": {"product_name": "teclados"}}', "¿Hay stock de ratones?", "no aparece"),
        ('{"ticket": {"ticket_id": "muchos"}}', "¿Estado del ticket 482?", "contrato"),
        ("Usa la tool de tickets", "¿Estado del ticket 482?", "JSON"),
    ],
)
def test_llm_decisions_not_grounded_in_the_question_are_rejected(text, question, why):
    with pytest.raises(routing.RouteRejected, match=why):
        routing.parse_llm_decision(text, question)


def test_a_decision_without_sources_falls_back_to_the_rag():
    decision = routing.parse_llm_decision('{"needs_rag": false, "ticket": null, "inventory": null}', "hola")
    assert decision.sources == ["rag"]


def fake_llm(monkeypatch, content=None, error=None):
    def create(**kwargs):
        if error:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(rag_pipeline, "load_settings", lambda: SimpleNamespace(llm_model="modelo"))
    monkeypatch.setattr(rag_pipeline, "check_models", lambda settings: None)
    monkeypatch.setattr(rag_pipeline, "get_generation_client", lambda: client)


def test_decide_route_uses_the_llm_when_its_decision_is_valid(monkeypatch):
    fake_llm(monkeypatch, '{"needs_rag": true, "ticket": {"ticket_id": 5}, "inventory": null, "reason": "ticket + política"}')
    decision = routing.decide_route("¿Cómo va el ticket 5 y qué plazo tiene la devolución?")
    assert decision.decided_by == "llm"
    assert decision.sources == ["incidents", "rag"]


@pytest.mark.parametrize(
    "content, error",
    [(None, TimeoutError("LLM lento")), ('{"needs_rag": false, "ticket": {"ticket_id": 999}}', None), ("no sé", None)],
)
def test_decide_route_falls_back_to_rules_when_the_llm_fails(monkeypatch, content, error):
    fake_llm(monkeypatch, content, error)
    decision = routing.decide_route("¿En qué estado está el ticket 5?")
    assert decision.decided_by == "rules"
    assert decision.ticket.ticket_id == 5
    assert "LLM descartado" in decision.reason


# --------------------------------------------------------------------------- #
# Respuestas con plantilla
# --------------------------------------------------------------------------- #
TICKET = {
    "id": "5", "title": "Paquete retrasado", "description": "d", "category": "DELAYED_DELIVERY",
    "status": "resolved", "origin": "customer", "branch": "Los Angeles",
    "created_at": "2026-11-01T10:00:00", "updated_at": "2026-11-03T10:00:00",
}


def test_ticket_answer_is_built_only_from_the_tool_data():
    result = {"tool": "incidents", "status": "ok", "query": {"ticket_id": 5}, "records": [TICKET], "total": 1}
    text = answers.tool_section(result)
    assert "El ticket 5 «Paquete retrasado» está resuelto" in text
    assert "Fuente: gestor de incidentes" in text


@pytest.mark.parametrize(
    "result",
    [
        {"tool": "incidents", "status": "unavailable", "query": {"ticket_id": 5}, "records": [], "total": 0},
        {"tool": "incidents", "status": "not_found", "query": {"ticket_id": 5}, "records": [], "total": 0},
        {"tool": "inventory", "status": "unavailable", "query": {"sku": "TF-1"}, "records": [], "total": 0},
        {"tool": "inventory", "status": "not_found", "query": {"product_name": "cajas"}, "records": [], "total": 0},
    ],
)
def test_fallback_messages_are_honest_and_never_state_a_status_or_stock(result):
    text = answers.fallback_message(result)
    assert text.startswith(("No he podido confirmar", "No encuentro"))
    assert not any(label in text for label in answers.STATUS_LABELS.values())
    assert "unidades" not in text
