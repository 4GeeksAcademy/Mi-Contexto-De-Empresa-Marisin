"""Orquestador y synthesizer del flujo RFP (Hito 9 · Parte 1).

El orquestador solo activa los departamentos que el alcance pide (BRIEFING §2.1
y §4) y manda a «sin asignar» lo que no cubre ningún departamento; el
synthesizer arma el handoff para la Parte 2 y señala contradicciones sin
resolverlas.
"""

from data.pipelines.rfp_intake import metadata as metadata_agent
from data.pipelines.rfp_intake import orchestrator, synthesizer
from data.pipelines.rfp_intake.schemas import DepartmentSection, KeyAspect
from rfp_helpers import FORMAL, INFORMAL, ScriptedLLM, load, offline_llm


def plan(fixture, llm=offline_llm):
    markdown = load(fixture)
    rfp_metadata = metadata_agent.rules_metadata(markdown)
    return orchestrator.plan_workstreams(markdown, rfp_metadata, llm=llm), rfp_metadata


def test_modaviva_activates_warehouse_and_reverse_but_not_lastmile():
    result, _ = plan(FORMAL)

    assert [w["department_id"] for w in result["workstreams"]] == ["warehouse", "reverse"]
    assert result["inactive_departments"] == [
        {
            "department_id": "lastmile",
            "reason": "excluido explícitamente en la RFP",
            "evidence": "mantenemos nuestro propio transportista para el reparto de última milla",
        }
    ]


def test_luna_activates_warehouse_and_lastmile_but_not_reverse():
    result, _ = plan(INFORMAL)

    assert [w["department_id"] for w in result["workstreams"]] == ["warehouse", "lastmile"]
    assert result["inactive_departments"][0]["department_id"] == "reverse"
    assert result["inactive_departments"][0]["reason"] == "el cliente no lo solicita"


def test_each_workstream_only_carries_excerpts_of_its_department():
    result, _ = plan(FORMAL)
    by_department = {w["department_id"]: w["excerpts"] for w in result["workstreams"]}

    assert any("15.000 SKUs" in excerpt for excerpt in by_department["warehouse"])
    assert not any("15.000 SKUs" in excerpt for excerpt in by_department["reverse"])
    assert any("reacondicionamiento" in excerpt for excerpt in by_department["reverse"])
    assert all("Proposals must be submitted" not in excerpt for excerpts in by_department.values() for excerpt in excerpts)


def test_the_llm_cannot_activate_a_department_the_client_did_not_ask_for():
    llm = ScriptedLLM(orchestrator={
        "workstreams": [
            {"department_id": "warehouse", "instructions": "Capacidad para 15.000 SKUs.",
             "excerpts": ["Almacenamiento de aproximadamente 15.000 SKUs en un centro cercano a Zaragoza"]},
            {"department_id": "lastmile", "instructions": "Cotizar envíos.", "excerpts": []},
        ],
        "out_of_scope": [],
    })

    result, _ = plan(FORMAL, llm=llm)

    assert [w["department_id"] for w in result["workstreams"]] == ["warehouse", "reverse"]
    assert any("lastmile" in warning for warning in result["warnings"])
    assert result["workstreams"][0]["instructions"] == "Capacidad para 15.000 SKUs."


def test_an_unknown_department_goes_to_unassigned_for_the_commercial_director():
    """Pregunta de diseño 1: un departamento que no existe en el BRIEFING no se pierde ni se inventa."""
    llm = ScriptedLLM(orchestrator={
        "workstreams": [{"department_id": "customs", "instructions": "Despacho de aduanas para Portugal.", "excerpts": []}],
        "out_of_scope": [{"topic": "Integración tecnológica", "evidence": "Integración con nuestro ERP vía API"}],
    })

    result, _ = plan(FORMAL, llm=llm)

    topics = {item["topic"]: item for item in result["unassigned_requests"]}
    assert "customs" in topics
    assert topics["customs"]["ask"] == "Miguel Torres"
    assert topics["Integración tecnológica"]["evidence"] == "Integración con nuestro ERP vía API"
    assert [w["department_id"] for w in result["workstreams"]] == ["warehouse", "reverse"]


def test_excerpts_that_are_not_literal_are_discarded():
    llm = ScriptedLLM(orchestrator={
        "workstreams": [{"department_id": "reverse", "instructions": "Devoluciones.",
                         "excerpts": ["Devoluciones del 30 % en 24 horas", "Gestión de devoluciones: inspección, reacondicionamiento y restock"]}],
    })

    result, _ = plan(FORMAL, llm=llm)

    reverse = next(w for w in result["workstreams"] if w["department_id"] == "reverse")
    assert "Devoluciones del 30 % en 24 horas" not in reverse["excerpts"]
    assert reverse["excerpts"][0] == "Gestión de devoluciones: inspección, reacondicionamiento y restock"


def test_customs_requests_in_the_document_are_detected_without_llm():
    markdown = load(INFORMAL) + "\nWe will also need help with customs clearance for imports from Korea.\n"
    rfp_metadata = metadata_agent.rules_metadata(markdown)

    result = orchestrator.plan_workstreams(markdown, rfp_metadata, llm=offline_llm)

    assert any(item["topic"].startswith("aduanas") for item in result["unassigned_requests"])


# --------------------------------------------------------------------------- #
# Synthesizer
# --------------------------------------------------------------------------- #
def section(department_id, responsible, name, detail, evidence="ev"):
    return DepartmentSection(
        department_id=department_id, department_name=name, responsible=responsible,
        key_aspects=[KeyAspect(topic="Volumen", detail=detail, evidence=evidence)], open_questions=["¿Peso?"],
    )


def test_the_handoff_contract_carries_ticket_id_and_key_aspects_for_part_two():
    _, rfp_metadata = plan(INFORMAL)
    sections = [
        section("lastmile", "Carlos Vega", "Last Mile and Carrier Management", "5000 pedidos al mes."),
        section("warehouse", "Ana Whitfield", "Warehouse Operations", "5000 pedidos al mes."),
    ]

    handoff = synthesizer.synthesize(
        ticket_id=7, rfp_id="abc", metadata=rfp_metadata, sections=sections,
        inactive_departments=[], unassigned_requests=[], excluded_services=[], readability={"word_count": 120},
        llm=offline_llm,
    )

    assert handoff["contract"] == "trackflow.rfp_intake.handoff/v1"
    assert handoff["ticket_id"] == 7
    assert handoff["next_status"] == "generando_borrador"
    assert handoff["ready_for_drafting"] is True
    assert handoff["client"]["currency"] == "USD"
    assert [d["department_id"] for d in handoff["departments"]] == ["warehouse", "lastmile"]
    assert handoff["departments"][0]["key_aspects"][0]["detail"] == "5000 pedidos al mes."
    assert handoff["departments"][0]["ask"].startswith("Pedir a Ana Whitfield")
    assert handoff["conflicts"] == []
    assert handoff["summary_source"] == "rules"
    assert "Ana Whitfield" in handoff["summary"] and "Carlos Vega" in handoff["summary"]


def test_contradictory_volumes_between_workers_are_flagged_not_resolved():
    """Pregunta de diseño 4: dos workers con cifras distintas → conflicto para Ventas."""
    _, rfp_metadata = plan(INFORMAL)
    sections = [
        section("warehouse", "Ana Whitfield", "Warehouse Operations", "5000 pedidos al mes."),
        section("lastmile", "Carlos Vega", "Last Mile and Carrier Management", "6000 pedidos al mes."),
    ]

    handoff = synthesizer.synthesize(
        ticket_id=1, rfp_id="x", metadata=rfp_metadata, sections=sections, inactive_departments=[],
        unassigned_requests=[], excluded_services=[], readability=None, llm=offline_llm,
    )

    conflict = handoff["conflicts"][0]
    assert conflict["type"] == "volume-mismatch"
    assert conflict["ask"] == "Miguel Torres"
    assert handoff["departments"][1]["key_aspects"][0]["detail"] == "6000 pedidos al mes."  # no se reescribe


def test_an_llm_summary_with_invented_figures_is_replaced_by_the_template():
    _, rfp_metadata = plan(INFORMAL)
    sections = [section("warehouse", "Ana Whitfield", "Warehouse Operations", "Almacén en LA.")]
    llm = ScriptedLLM(synthesizer="Luna Cosmetics pide 12.000 pedidos al mes; Ana Whitfield cotiza el almacén.")

    handoff = synthesizer.synthesize(
        ticket_id=1, rfp_id="x", metadata=rfp_metadata, sections=sections, inactive_departments=[],
        unassigned_requests=[], excluded_services=[], readability=None, llm=llm,
    )

    assert handoff["summary_source"] == "rules"
    assert "12.000" not in handoff["summary"]


def test_a_grounded_llm_summary_is_used():
    _, rfp_metadata = plan(INFORMAL)
    sections = [section("warehouse", "Ana Whitfield", "Warehouse Operations", "5000 pedidos al mes.")]
    text = "Luna Cosmetics (EE. UU.) pide almacenamiento para unos 5000 pedidos al mes; se cotiza en USD. Ana Whitfield debe confirmar la capacidad."

    handoff = synthesizer.synthesize(
        ticket_id=1, rfp_id="x", metadata=rfp_metadata, sections=sections, inactive_departments=[],
        unassigned_requests=[], excluded_services=[], readability=None, llm=ScriptedLLM(synthesizer=text),
    )

    assert handoff["summary_source"] == "llm"
    assert handoff["summary"] == text


def test_unknown_country_is_flagged_as_a_currency_conflict():
    _, rfp_metadata = plan(INFORMAL)
    rfp_metadata = rfp_metadata.model_copy(update={"client_country": None, "currency": None})

    handoff = synthesizer.synthesize(
        ticket_id=1, rfp_id="x", metadata=rfp_metadata, sections=[], inactive_departments=[],
        unassigned_requests=[], excluded_services=[], readability=None, llm=offline_llm,
    )

    assert [c["type"] for c in handoff["conflicts"]] == ["currency-unknown"]
    assert handoff["ready_for_drafting"] is False
