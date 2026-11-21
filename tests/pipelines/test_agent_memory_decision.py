"""Clasificador de la decisión del usuario sobre la propuesta pendiente (LLM + guardas + reglas).

    python -m pytest tests/pipelines/test_agent_memory_decision.py
"""

import json

import pytest

from services.agent.memory import decision
from services.agent.memory.models import Actor, MemoryDraft, PendingProposal

PENDING = PendingProposal(
    proposal_id="p-1", conversation_id="c-1", created_at="2026-11-22T10:00:00+00:00",
    expires_at="2026-11-22T10:30:00+00:00", proposed_to=Actor(user_id=7), origin_message="…",
    draft=MemoryDraft(category="carrier_rule", carrier="SEUR", country="ES", zone="zona rural de Zaragoza",
                      fact="SEUR ya no cubre la zona rural de Zaragoza: usar el carrier local."),
    slot_id="carrier_rule:SEUR:ES", fact_key="zona-rural-de-zaragoza",
)


def llm(label, confidence=0.95, **extra):
    return json.dumps({"label": label, "confidence": confidence, **extra}, ensure_ascii=False)


@pytest.mark.parametrize(
    "message, output, label, remaining",
    [
        ("sí, recuérdalo", llm("approve"), "approve", ""),
        ("no, eso no es así", llm("reject"), "reject", ""),
        # Responde y sigue preguntando en el mismo mensaje
        ("Sí, guárdalo. Y ¿cuál es la ventana de devolución estándar?",
         llm("approve", remaining_question="¿cuál es la ventana de devolución estándar?"),
         "approve", "¿cuál es la ventana de devolución estándar?"),
        # Cambio de tema sin responder
        ("¿En qué estado está el ticket 3?", llm("unrelated"), "unrelated", "¿En qué estado está el ticket 3?"),
        ("mmm, no sé", llm("unclear", 0.4), "unclear", ""),
    ],
)
def test_llm_labels_are_parsed_against_the_pending_proposal(message, output, label, remaining):
    result = decision.parse_llm_decision(output, message, PENDING)
    assert result.label == label
    assert result.remaining_question == remaining
    assert result.decided_by == "llm"


def test_low_confidence_is_never_an_approval():
    result = decision.parse_llm_decision(llm("approve", 0.6), "puede", PENDING)
    assert result.label == "unclear"


def test_an_approval_that_starts_with_a_negation_is_ambiguous():
    assert decision.parse_llm_decision(llm("approve"), "no, mejor guárdalo luego", PENDING).label == "unclear"


def test_a_rejection_that_starts_with_yes_is_ambiguous():
    assert decision.parse_llm_decision(llm("reject"), "sí", PENDING).label == "unclear"


def test_an_edit_must_come_from_the_users_words():
    ok = decision.parse_llm_decision(
        llm("edit", edited_fact="SEUR ya no cubre la zona rural de Zaragoza desde diciembre: usar el carrier local."),
        "sí, pero es desde diciembre", PENDING,
    )
    assert ok.label == "edit" and "diciembre" in ok.edited_fact

    invented = decision.parse_llm_decision(
        llm("edit", edited_fact="MRW cubre ahora toda Aragón con tarifa plana."), "sí, pero es desde diciembre", PENDING,
    )
    assert invented.label == "unclear" and invented.edited_fact is None


def test_an_invented_remaining_question_is_replaced_by_the_message():
    result = decision.parse_llm_decision(
        llm("unrelated", remaining_question="¿Cuál es el stock del SKU TF-1?"), "¿qué tarifas tiene MRW?", PENDING
    )
    assert result.remaining_question == "¿qué tarifas tiene MRW?"


@pytest.mark.parametrize("text", ["no es JSON", "[1, 2]", llm("maybe"), llm("approve", 1.7)])
def test_invalid_llm_output_is_rejected(text):
    with pytest.raises(decision.DecisionRejected):
        decision.parse_llm_decision(text, "sí", PENDING)


@pytest.mark.parametrize(
    "message, label",
    [
        ("Sí", "approve"), ("vale, guárdalo", "approve"), ("De acuerdo.", "approve"),
        ("No", "reject"), ("no, gracias", "reject"), ("Mejor no", "reject"),
        # No es una frase completa de sí/no: no se interpreta (no es un `"sí" in mensaje`)
        ("sí, aunque no estoy seguro", "unclear"), ("así es como lo hacemos", "unclear"),
        ("¿y si no?", "unclear"), ("¿Cuál es el SLA de entrega?", "unclear"),
    ],
)
def test_rules_fallback_only_accepts_whole_yes_or_no_phrases(message, label):
    result = decision.classify_with_rules(message)
    assert result.label == label
    if label == "unclear":
        assert result.remaining_question == message


def test_falls_back_to_rules_when_the_llm_fails(monkeypatch):
    def broken(pending, message):
        raise TimeoutError("sin LLM")

    monkeypatch.setattr(decision, "classify_with_llm", broken)
    assert decision.classify_decision(PENDING, "sí").label == "approve"
    assert decision.classify_decision(PENDING, "sí, y ¿el stock de cajas?").label == "unclear"
