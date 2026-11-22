"""Agente clasificador del flujo RFP (Hito 9 · Parte 1).

Casos del BRIEFING §4: la RFP formal (ModaViva) y la informal (Luna Cosmetics) se
aceptan; el pitch de tarifas de RapidShip se rechaza. Se prueba la decisión del
LLM (con un doble), su validación y el respaldo por reglas.
"""

import pytest

from data.pipelines.rfp_intake import classifier
from rfp_helpers import FORMAL, INFORMAL, INVALID, ScriptedLLM, load, offline_llm


def llm_says(**decision):
    return ScriptedLLM(classifier=decision)


@pytest.mark.parametrize(
    ("fixture", "is_rfp", "document_type"),
    [(FORMAL, True, "formal_rfp"), (INFORMAL, True, "informal_request"), (INVALID, False, "vendor_pitch")],
)
def test_rules_classify_the_three_briefing_samples(fixture, is_rfp, document_type):
    decision = classifier.classify_with_rules(load(fixture))

    assert decision.is_rfp is is_rfp
    assert decision.document_type == document_type
    assert decision.source == "rules"
    assert decision.reason


def test_without_llm_the_rules_decide_and_the_error_is_recorded():
    decision = classifier.classify_document(load(INVALID), llm=offline_llm)

    assert decision.is_rfp is False
    assert decision.source == "rules"
    assert "sin LLM" in decision.second_opinion["llm_error"]


def test_a_valid_llm_decision_is_used_and_the_rules_are_kept_as_second_opinion():
    llm = llm_says(is_rfp=True, document_type="informal_request", confidence=0.93,
                   reason="Correo de una marca que pide propuesta de almacenamiento y envíos en EE. UU.")

    decision = classifier.classify_document(load(INFORMAL), llm=llm)

    assert decision.source == "llm"
    assert decision.is_rfp is True
    assert decision.confidence == 0.93
    assert decision.second_opinion["source"] == "rules"
    assert decision.second_opinion["is_rfp"] is True
    assert llm.roles_called() == ["classifier"]


def test_the_llm_reads_the_converted_markdown_not_the_pdf():
    llm = llm_says(is_rfp=False, document_type="vendor_pitch", confidence=0.9, reason="Pitch de transportista.")

    classifier.classify_document(load(INVALID), llm=llm)

    _, user = llm.calls[0]
    assert "<documento>" in user
    assert "Exclusive shipping rates for TrackFlow" in user


def test_the_llm_rejects_a_vendor_pitch_and_the_ticket_can_be_discarded():
    llm = llm_says(is_rfp=False, document_type="vendor_pitch", confidence=0.95,
                   reason="RapidShip ofrece sus tarifas a TrackFlow; no pide una propuesta.")

    decision = classifier.classify_document(load(INVALID), llm=llm)

    assert decision.is_rfp is False
    assert decision.document_type == "vendor_pitch"
    assert "RapidShip" in decision.reason


@pytest.mark.parametrize(
    "raw",
    [
        "Sí, es una RFP.",  # sin JSON
        '{"is_rfp": "quizá", "document_type": "formal_rfp", "confidence": 0.9, "reason": "x"}',  # tipo inválido
        '{"is_rfp": true, "document_type": "vendor_pitch", "confidence": 0.9, "reason": "x"}',  # contradicción
        '{"is_rfp": true, "document_type": "formal_rfp", "confidence": 3, "reason": "x"}',  # fuera de rango
        '{"is_rfp": true, "document_type": "formal_rfp", "confidence": 0.9, "reason": ""}',  # sin motivo
    ],
)
def test_llm_output_that_breaks_the_contract_falls_back_to_the_rules(raw):
    decision = classifier.classify_document(load(INVALID), llm=lambda system, user: raw)

    assert decision.source == "rules"
    assert decision.is_rfp is False
    assert "ClassifierOutputError" in decision.second_opinion["llm_error"]


def test_a_low_confidence_llm_decision_does_not_discard_a_real_rfp():
    """Falso negativo: el LLM duda y diría «no es RFP»; con confianza baja deciden las reglas."""
    llm = llm_says(is_rfp=False, document_type="other", confidence=0.4, reason="No estoy seguro.")

    decision = classifier.classify_document(load(FORMAL), llm=llm)

    assert decision.is_rfp is True
    assert decision.source == "rules"
    assert decision.second_opinion == {
        "source": "llm", "is_rfp": False, "document_type": "other", "confidence": 0.4, "reason": "No estoy seguro.",
    }


def test_json_wrapped_in_a_code_fence_is_accepted():
    raw = '```json\n{"is_rfp": true, "document_type": "formal_rfp", "confidence": 0.88, "reason": "Pliego formal."}\n```'

    decision = classifier.classify_document(load(FORMAL), llm=lambda system, user: raw)

    assert decision.source == "llm"
    assert decision.document_type == "formal_rfp"


def test_a_document_that_asks_nothing_from_trackflow_is_not_an_rfp():
    newsletter = "# Newsletter de noviembre\n\nEste mes hablamos de tendencias de moda sostenible y de nuestro nuevo blog.\n"

    decision = classifier.classify_with_rules(newsletter)

    assert decision.is_rfp is False
    assert decision.document_type == "other"
