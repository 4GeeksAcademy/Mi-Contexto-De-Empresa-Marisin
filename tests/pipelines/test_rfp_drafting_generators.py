"""Agentes generadores de la Parte 2 (uno por departamento) y su entrada desde el handoff de la Parte 1.

Sin LangGraph ni BD: cada generador recibe solo su `DraftingInput` (slice del
handoff + tarifa + políticas) y devuelve un borrador de su sección de la
propuesta económica. Sin LLM usa su plantilla, que ya cumple el BRIEFING §5.
"""

import pytest

from data.pipelines.rfp_intake.drafting import evaluators, generators, handoff as contract, knowledge
from rfp_helpers import FORMAL, INFORMAL, ScriptedLLM, offline_handoff, offline_llm


def inputs_for(fixture):
    return {context.department_id: context for context in contract.drafting_inputs(offline_handoff(fixture, 7))}


def evaluate(content, context):
    return (
        evaluators.evaluate_readability(content),
        evaluators.evaluate_relevance(
            content, department_id=context.department_id, client_name=context.client_name,
            key_aspects=context.key_aspects, open_questions=context.open_questions,
        ),
        evaluators.evaluate_compliance(content, currency=context.currency, sources=contract.anchor_sources(context)),
    )


def test_each_department_has_its_own_generator_agent():
    agents = generators.GENERATORS

    assert set(agents) == {"warehouse", "lastmile", "reverse"}
    assert len({type(agent) for agent in agents.values()}) == 3
    assert "Ana Whitfield" in agents["warehouse"].system_prompt()
    assert "Carlos Vega" in agents["lastmile"].system_prompt()
    assert "Sofía Ramos" in agents["reverse"].system_prompt()


def test_the_input_comes_from_the_part1_handoff_only_for_active_departments():
    formal = inputs_for(FORMAL)
    informal = inputs_for(INFORMAL)

    assert list(formal) == ["warehouse", "reverse"]  # ModaViva: sin lastmile
    assert list(informal) == ["warehouse", "lastmile"]  # Luna: sin reverse
    assert formal["warehouse"].currency == "EUR" and informal["lastmile"].currency == "USD"
    assert informal["lastmile"].monthly_volume == 5000
    assert "markdown" not in formal["warehouse"].model_dump()  # nunca el documento completo


def test_a_generator_only_sees_its_own_department():
    context = inputs_for(FORMAL)["reverse"]
    llm = ScriptedLLM(draft_reverse="## Propuesta económica — Reverse Logistics\nTexto.")

    generators.generator_for("reverse").generate(context, llm=llm)

    role, user = llm.calls[0]
    assert role == "draft_reverse"
    assert "Sofía Ramos" in user
    assert "Ana Whitfield" not in user  # nada de la sección de warehouse
    assert "returns-policy" in user  # su política de la base de conocimiento


@pytest.mark.parametrize(("fixture", "department_id"), [
    (FORMAL, "warehouse"), (FORMAL, "reverse"), (INFORMAL, "warehouse"), (INFORMAL, "lastmile"),
])
def test_the_template_of_every_generator_passes_its_evaluation(fixture, department_id):
    context = inputs_for(fixture)[department_id]

    draft = generators.generator_for(department_id).generate(context, llm=offline_llm)
    readability, relevance, compliance = evaluate(draft.content, context)

    assert draft.source == "rules"
    assert readability.passed, readability.details
    assert relevance.passed, relevance.missing_aspects
    assert compliance.passed, compliance.violations


def test_the_template_quotes_in_the_client_currency_with_sla_and_discounts():
    eur = generators.generator_for("warehouse").template(inputs_for(FORMAL)["warehouse"])
    usd = generators.generator_for("lastmile").template(inputs_for(INFORMAL)["lastmile"])

    assert "16 EUR" in eur and "USD" not in eur and "Zaragoza" in eur
    assert "6,90 USD" in usd and "EUR" not in usd
    for content in (eur, usd):
        assert "90 % de entregas a tiempo" in content
        assert "| Pedidos al mes | Descuento por volumen |" in content
    assert "Con 5.000 pedidos al mes, Luna Cosmetics entra en el tramo «5.000 a 9.999»" in usd
    assert "La RFP no indica el volumen mensual" in eur  # ModaViva no lo dice: no se inventa


def test_open_questions_of_part1_go_to_pending_data():
    context = inputs_for(FORMAL)["warehouse"]

    content = generators.generator_for("warehouse").template(context)

    assert context.open_questions
    assert "### Datos pendientes del cliente" in content
    assert all(question in content for question in context.open_questions)


def test_the_llm_draft_is_used_when_available():
    context = inputs_for(INFORMAL)["lastmile"]
    llm = ScriptedLLM(draft_lastmile="```markdown\n## Propuesta económica — Last Mile\nBorrador del LLM.\n```")

    draft = generators.generator_for("lastmile").generate(context, iteration=1, llm=llm)

    assert draft.source == "llm"
    assert draft.content == "## Propuesta económica — Last Mile\nBorrador del LLM."


def test_a_rewrite_receives_the_previous_draft_and_the_concrete_feedback():
    context = inputs_for(FORMAL)["reverse"]
    llm = ScriptedLLM(draft_reverse="## Propuesta económica — Reverse Logistics\nCorregido.")
    feedback = "- [returns-min-48h] Quita la promesa «Procesamos las devoluciones en 24 horas»."

    generators.generator_for("reverse").generate(
        context, iteration=2, previous="Procesamos las devoluciones en 24 horas.", feedback=feedback, llm=llm
    )

    user = llm.calls[0][1]
    assert "NO PASÓ LA EVALUACIÓN" in user
    assert feedback in user
    assert "Procesamos las devoluciones en 24 horas." in user


def test_without_currency_the_generator_does_not_quote_prices():
    handoff = offline_handoff(FORMAL, 7)
    handoff["client"]["currency"] = None
    context = contract.drafting_inputs(handoff)[0]

    content = generators.generator_for(context.department_id).template(context)

    assert context.reference == ""
    assert "No se puede cotizar" in content


def test_semantic_knowledge_falls_back_to_the_policy_files(monkeypatch):
    def broken(department_id):
        raise ConnectionError("Qdrant parado")

    monkeypatch.setattr(knowledge, "semantic_snippets", broken)

    snippets = knowledge.snippets_for("warehouse", mode="semantic")

    assert [s["document_id"] for s in snippets] == ["storage-pricing", "sla-delivery"]
    assert "18 USD por metro cúbico" in snippets[0]["text"]
