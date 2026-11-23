"""Workers por departamento del flujo RFP (Hito 9 · Parte 1).

Cada worker recibe metadatos + extractos de su departamento y devuelve
`key_aspects` con evidencia y `open_questions`. Lo central: nunca inventa
volúmenes ni cifras que no estén en la RFP (BRIEFING §2.3).
"""

from data.pipelines.rfp_intake import metadata as metadata_agent
from data.pipelines.rfp_intake import orchestrator, workers
from data.pipelines.rfp_intake.schemas import Workstream
from rfp_helpers import FORMAL, INFORMAL, ScriptedLLM, load, offline_llm


def workstream_for(fixture, department_id):
    markdown = load(fixture)
    rfp_metadata = metadata_agent.rules_metadata(markdown)
    plan = orchestrator.plan_workstreams(markdown, rfp_metadata, llm=offline_llm)
    workstream = next(w for w in plan["workstreams"] if w["department_id"] == department_id)
    return Workstream.model_validate(workstream), rfp_metadata


def test_warehouse_worker_without_volume_asks_for_it_instead_of_inventing_it():
    workstream, rfp_metadata = workstream_for(FORMAL, "warehouse")
    llm = ScriptedLLM(warehouse={
        "key_aspects": [
            {"topic": "SKUs a almacenar", "detail": "Unos 15.000 SKUs cerca de Zaragoza.",
             "evidence": "Almacenamiento de aproximadamente 15.000 SKUs en un centro cercano a Zaragoza"},
            {"topic": "Volumen de pedidos", "detail": "Unos 8.000 pedidos al mes.",
             "evidence": "Almacenamiento de aproximadamente 15.000 SKUs en un centro cercano a Zaragoza"},
        ],
        "open_questions": [],
    })

    section = workers.run_department_worker(workstream, rfp_metadata, llm=llm)

    assert rfp_metadata.monthly_volume is None
    assert [aspect.topic for aspect in section.key_aspects] == ["SKUs a almacenar"]
    assert any("8000" in warning for warning in section.warnings)
    assert any("volumen mensual" in question for question in section.open_questions)
    assert section.source == "llm"


def test_the_responsible_comes_from_the_briefing_not_from_the_llm():
    workstream, rfp_metadata = workstream_for(INFORMAL, "lastmile")
    llm = ScriptedLLM(lastmile={
        "responsible": "Otra Persona",
        "key_aspects": [{"topic": "Selección de transportista", "detail": "El cliente no tiene transportistas.",
                         "evidence": "we don't have relationships with any carriers yet"}],
        "open_questions": ["¿Peso medio de los paquetes?"],
    })

    section = workers.run_department_worker(workstream, rfp_metadata, llm=llm)

    assert section.responsible == "Carlos Vega"
    assert section.department_name == "Last Mile and Carrier Management"


def test_aspects_whose_evidence_is_not_in_the_excerpts_are_discarded():
    workstream, rfp_metadata = workstream_for(INFORMAL, "lastmile")
    llm = ScriptedLLM(lastmile={
        "key_aspects": [{"topic": "Entrega en 24 h", "detail": "El cliente pide entrega al día siguiente.",
                         "evidence": "We require next-day delivery to every state"}],
        "open_questions": [],
    })

    section = workers.run_department_worker(workstream, rfp_metadata, llm=llm)

    assert all(aspect.topic != "Entrega en 24 h" for aspect in section.key_aspects)
    assert section.source == "rules"  # todo lo del LLM se descartó: aspectos literales
    assert section.key_aspects
    assert all(aspect.evidence in " ".join(section.excerpts) or "monthly_volume" in aspect.evidence
               for aspect in section.key_aspects)


def test_the_lastmile_worker_keeps_the_real_monthly_volume():
    workstream, rfp_metadata = workstream_for(INFORMAL, "lastmile")

    section = workers.run_department_worker(workstream, rfp_metadata, llm=offline_llm)

    assert rfp_metadata.monthly_volume == 5000
    assert section.key_aspects[0].topic == "Volumen mensual"
    assert "5,000 orders a month" in section.key_aspects[0].evidence
    assert not any("envíos al mes" in question for question in section.open_questions)
    assert any("peso" in question for question in section.open_questions)


def test_without_llm_the_worker_still_returns_literal_aspects_and_open_questions():
    workstream, rfp_metadata = workstream_for(FORMAL, "reverse")

    section = workers.run_department_worker(workstream, rfp_metadata, llm=offline_llm)

    assert section.source == "rules"
    assert section.responsible == "Sofía Ramos"
    assert any("inspección, reacondicionamiento y restock" in aspect.detail for aspect in section.key_aspects)
    assert any("tasa de devoluciones" in question for question in section.open_questions)
    assert any("worker LLM no disponible" in warning for warning in section.warnings)


def test_the_worker_only_receives_its_own_excerpts_and_the_shared_metadata():
    workstream, rfp_metadata = workstream_for(FORMAL, "reverse")
    llm = ScriptedLLM(reverse={"key_aspects": [], "open_questions": []})

    workers.run_department_worker(workstream, rfp_metadata, llm=llm)

    _, user = llm.calls[0]
    assert "METADATOS COMPARTIDOS" in user
    assert "devoluciones" in user
    assert "Integración con nuestro ERP vía API" not in user  # extracto de warehouse
    assert "Proposals must be submitted electronically" not in user  # resto del documento


def test_open_questions_with_invented_figures_are_dropped():
    workstream, rfp_metadata = workstream_for(FORMAL, "warehouse")
    llm = ScriptedLLM(warehouse={
        "key_aspects": [{"topic": "Integración", "detail": "Integración con su ERP vía API.",
                         "evidence": "Integración con nuestro ERP vía API"}],
        "open_questions": ["¿Confirman los 1.200 pallets?", "¿Qué ERP usan?"],
    })

    section = workers.run_department_worker(workstream, rfp_metadata, llm=llm)

    assert "¿Qué ERP usan?" in section.open_questions
    assert all("1.200" not in question for question in section.open_questions)


def test_llm_rewordings_of_the_required_questions_are_not_repeated():
    workstream, rfp_metadata = workstream_for(FORMAL, "warehouse")
    llm = ScriptedLLM(warehouse={
        "key_aspects": [{"topic": "SKUs a almacenar", "detail": "Unos 15.000 SKUs.",
                         "evidence": "Almacenamiento de aproximadamente 15.000 SKUs en un centro cercano a Zaragoza"}],
        "open_questions": ["¿Cuántos pedidos mensuales?", "¿Unidades por SKU o pallets?"],
    })

    section = workers.run_department_worker(workstream, rfp_metadata, llm=llm)

    assert len([q for q in section.open_questions if "pedidos" in q]) == 1
    assert "¿Unidades por SKU o pallets?" in section.open_questions
