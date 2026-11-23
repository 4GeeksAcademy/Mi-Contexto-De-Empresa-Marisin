"""Agentes evaluadores de la Parte 2: legibilidad, pertinencia y cumplimiento del BRIEFING.

Cada fallo de cumplimiento está anclado a una regla concreta del BRIEFING §5
(o §2.3 «nunca inventes») con su `rule_id`, y el `EvaluationResult` tiene la
forma del enunciado (readability / relevance / compliance + overall_pass +
feedback_for_generator).
"""

import pytest

from data.pipelines.rfp_intake.drafting import config, evaluators, generators, handoff as contract
from rfp_helpers import FORMAL, INFORMAL, offline_handoff


@pytest.fixture(scope="module")
def reverse_es():
    """Sección de devoluciones de ModaViva (España → EUR) generada con la plantilla."""
    context = next(c for c in contract.drafting_inputs(offline_handoff(FORMAL, 3)) if c.department_id == "reverse")
    return context, generators.generator_for("reverse").template(context)


@pytest.fixture(scope="module")
def lastmile_us():
    context = next(c for c in contract.drafting_inputs(offline_handoff(INFORMAL, 4)) if c.department_id == "lastmile")
    return context, generators.generator_for("lastmile").template(context)


def compliance(content, context):
    return evaluators.evaluate_compliance(content, currency=context.currency, sources=contract.anchor_sources(context))


def rule_ids(check):
    return [violation.rule_id for violation in check.violations]


# --------------------------------------------------------------------------- #
# Cumplimiento anclado al BRIEFING §5
# --------------------------------------------------------------------------- #
def test_briefing_rule_returns_under_48_hours_fails_compliance(reverse_es):
    """BRIEFING §5: «Ninguna propuesta puede prometer procesamiento de devoluciones en menos de 48 horas»."""
    context, content = reverse_es
    draft = content.replace("72 horas desde que llega al almacén", "24 horas desde que llega al almacén")

    check = compliance(draft, context)

    assert check.passed is False
    assert rule_ids(check) == [config.RULE_RETURNS_48H]
    assert "24 horas" in check.violations[0].evidence


def test_the_compliant_template_passes_every_rule(reverse_es):
    context, content = reverse_es

    check = compliance(content, context)

    assert check.passed is True
    assert check.rule_ids == list(config.COMPLIANCE_RULES)  # se comprueban las seis reglas


@pytest.mark.parametrize("sentence", [
    "Procesamos las devoluciones en menos de 48 horas.",
    "Las devoluciones se procesan en 1-2 días.",
    "Reacondicionamos cada devolución el mismo día.",
])
def test_every_way_of_promising_fast_returns_is_caught(reverse_es, sentence):
    context, content = reverse_es

    assert config.RULE_RETURNS_48H in rule_ids(compliance(content + "\n" + sentence + "\n", context))


def test_saying_we_never_promise_under_48_hours_is_not_a_promise(reverse_es):
    context, content = reverse_es
    draft = content + "\nTrackFlow nunca promete procesar devoluciones en menos de 48 horas.\n"

    assert compliance(draft, context).passed is True


def test_quoting_in_the_wrong_currency_fails(reverse_es):
    """BRIEFING §5: España se cotiza en EUR."""
    context, content = reverse_es
    draft = content.replace("| 2,40 EUR |", "| 2,40 USD |")

    check = compliance(draft, context)

    assert rule_ids(check) == [config.RULE_CURRENCY]
    assert "USD" in check.violations[0].detail


def test_without_country_there_is_no_valid_currency(reverse_es):
    _, content = reverse_es

    check = evaluators.evaluate_compliance(content, currency=None, sources=[content])

    assert config.RULE_CURRENCY in rule_ids(check)


def test_missing_on_time_sla_fails(lastmile_us):
    context, content = lastmile_us
    draft = "\n".join(line for line in content.splitlines() if "SLA de entrega a tiempo" not in line)

    assert rule_ids(compliance(draft, context)) == [config.RULE_SLA]


def test_missing_volume_discount_table_fails(lastmile_us):
    context, content = lastmile_us
    draft = "\n".join(line for line in content.splitlines() if not line.startswith("| ") or "Concepto" in line
                      or "Envío" in line)

    assert config.RULE_DISCOUNT_TABLE in rule_ids(compliance(draft, context))


def test_revealing_a_carrier_negotiated_rate_fails(lastmile_us):
    context, content = lastmile_us
    draft = content + "\n- Con UPS tenemos una tarifa negociada para paquetes de más de 5 kg.\n"

    check = compliance(draft, context)

    assert rule_ids(check) == [config.RULE_CARRIER_RATES]
    assert "UPS" in check.violations[0].evidence


def test_naming_carriers_without_rates_is_allowed(lastmile_us):
    context, content = lastmile_us
    draft = content + "\n- La red incluye UPS, FedEx y DHL; el sistema elige según destino y peso.\n"

    assert compliance(draft, context).passed is True


def test_invented_figures_fail(lastmile_us):
    """BRIEFING §2.3: nunca inventes volúmenes que no estén en la RFP."""
    context, content = lastmile_us
    draft = content + "\n- Calculamos 8.000 envíos al mes y 3,95 USD por envío exprés.\n"

    check = compliance(draft, context)

    assert rule_ids(check) == [config.RULE_NO_INVENTED_FIGURES]
    assert "8000" in check.violations[0].evidence and "3.95" in check.violations[0].evidence


# --------------------------------------------------------------------------- #
# Legibilidad y pertinencia
# --------------------------------------------------------------------------- #
def test_readability_uses_fernandez_huerta_for_spanish(reverse_es):
    _, content = reverse_es

    check = evaluators.evaluate_readability(content)

    assert check.passed is True
    assert check.details["metric"] == "fernandez_huerta"
    assert check.score == check.details["fernandez_huerta"]


def test_long_convoluted_sentences_fail_readability():
    sentence = (
        "La organización logística integral de las operaciones transfronterizas correspondientes a la "
        "administración centralizada de inventarios multicanal exige procedimientos documentados, "
        "verificaciones sistemáticas, conciliaciones periódicas y coordinación interdepartamental continuada "
        "entre los equipos responsables de almacenamiento, distribución, devoluciones y facturación"
    )
    check = evaluators.evaluate_readability(" ".join([sentence + ","] * 3) + " siempre.")

    assert check.passed is False
    assert any("palabras por frase" in problem for problem in check.details["problems"])


def test_relevance_reports_the_aspects_the_section_does_not_answer(reverse_es):
    context, _ = reverse_es
    short = "## Propuesta económica — Reverse Logistics\nModaViva: devoluciones a 2,40 EUR. Ver precios abajo."

    check = evaluators.evaluate_relevance(
        short, department_id="reverse", client_name=context.client_name,
        key_aspects=context.key_aspects, open_questions=context.open_questions,
    )

    assert check.passed is False
    assert any(item.startswith("aspecto clave «Inspección") for item in check.missing_aspects)
    assert any(item.startswith("pregunta abierta") for item in check.missing_aspects)


# --------------------------------------------------------------------------- #
# EvaluationResult y feedback
# --------------------------------------------------------------------------- #
def test_evaluation_result_has_the_shape_of_the_brief_and_concrete_feedback(reverse_es):
    context, content = reverse_es
    draft = content.replace("72 horas desde que llega al almacén", "24 horas desde que llega al almacén")
    result = evaluators.judge(
        ticket_id=3, department_id="reverse", iteration=1, currency="EUR",
        readability=evaluators.evaluate_readability(draft),
        relevance=evaluators.evaluate_relevance(
            draft, department_id="reverse", client_name=context.client_name,
            key_aspects=context.key_aspects, open_questions=context.open_questions,
        ),
        compliance=compliance(draft, context),
    )

    data = evaluators.evaluation_dict(result)

    assert data["section_id"] == "3:reverse" and data["department_id"] == "reverse"
    assert set(data["readability"]) >= {"pass", "score", "details"}
    assert set(data["relevance"]) >= {"pass", "missing_aspects"}
    assert set(data["compliance"]) == {"pass", "rule_ids", "violations"}
    assert data["overall_pass"] is False
    feedback = data["feedback_for_generator"]
    assert "[returns-min-48h]" in feedback and "24 horas" in feedback and "72 horas" in feedback


def test_a_passing_section_gets_no_changes_feedback(reverse_es):
    context, content = reverse_es
    result = evaluators.judge(
        ticket_id=3, department_id="reverse", iteration=1, currency="EUR",
        readability=evaluators.evaluate_readability(content),
        relevance=evaluators.evaluate_relevance(
            content, department_id="reverse", client_name=context.client_name,
            key_aspects=context.key_aspects, open_questions=context.open_questions,
        ),
        compliance=compliance(content, context),
    )

    assert result.overall_pass is True
    assert result.feedback_for_generator.startswith("Sin cambios")
