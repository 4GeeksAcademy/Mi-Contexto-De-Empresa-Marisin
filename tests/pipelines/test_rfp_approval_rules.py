"""Reglas deterministas de la Parte 3 (sin LangGraph): triggers, árbitro, decisión humana, documento y traza.

- Los triggers del BRIEFING §7 se detectan en estado estructurado (secciones,
  moneda del país, volumen del handoff), no por la opinión de un agente.
- El árbitro es fijo y aplica la regla del BRIEFING (`mode = "rule"`), con límite de rondas.
- La respuesta humana se valida antes de entrar al grafo.
"""

import pytest
from pydantic import ValidationError

from data.pipelines.rfp_intake.approval import arbiter, config, conflicts, document, trace
from data.pipelines.rfp_intake.approval.schemas import validate_decision

USD_TABLE = "| Concepto | Precio |\n|---|---|\n| Envío estándar hasta 2 kg | 6,90 USD |"
EUR_TABLE = "| Concepto | Precio |\n|---|---|\n| Almacenamiento por m³ | 16 EUR |"


def sections(**contents):
    return {department_id: {"draft_content": content} for department_id, content in contents.items()}


# --------------------------------------------------------------------------- #
# Triggers (BRIEFING §7)
# --------------------------------------------------------------------------- #
def test_volume_vs_capacity_fires_when_lastmile_assumes_more_than_the_warehouse_can_prepare():
    found = conflicts.detect_conflicts(
        sections(warehouse=USD_TABLE, lastmile=USD_TABLE + "\nCon 30.000 pedidos al mes entra en el tramo «25.000 o más»."),
        currency="USD", monthly_volume=30000,
    )

    assert [c.trigger for c in found] == [config.TRIGGER_VOLUME_CAPACITY]
    # El volumen del handoff también lo asume warehouse: las dos se limitan a la capacidad.
    assert found[0].departments == ["warehouse", "lastmile"]
    assert found[0].data == {"assumed_volume": 30000, "capacity": config.WAREHOUSE_MONTHLY_CAPACITY["USD"], "currency": "USD"}


def test_volume_within_capacity_quotes_and_discount_tiers_do_not_fire():
    content = (
        USD_TABLE + "\n- **Volumen:** el cliente indica «30,000 orders a month».\n"
        "| Pedidos al mes | Descuento |\n|---|---|\n| 25.000 o más | 12 % |\n"
        "A partir de 25.000 pedidos al mes el descuento es del 12 %.\nCon 5.000 pedidos al mes aplica el 5 %."
    )

    assert conflicts.assumed_volumes(content) == [5000]
    assert conflicts.detect_conflicts(sections(warehouse=USD_TABLE, lastmile=content), currency="USD", monthly_volume=5000) == []


def test_volume_vs_capacity_needs_both_departments_and_respects_the_arbiter_override():
    lastmile = USD_TABLE + "\nCon 20.000 pedidos al mes."
    assert conflicts.detect_conflicts(sections(lastmile=lastmile), currency="USD", monthly_volume=90000) == []
    assert conflicts.detect_conflicts(
        sections(warehouse=USD_TABLE, lastmile=lastmile), currency="USD", monthly_volume=30000,
        overrides={"lastmile": {"monthly_volume": 20000}},
    ) == []


def test_returns_sla_breach_points_at_the_section_that_promises_under_48_hours():
    found = conflicts.detect_conflicts(
        sections(warehouse=EUR_TABLE + "\n- Procesamos las devoluciones en 24 horas.", reverse=EUR_TABLE + "\n- 72 horas por devolución."),
        currency="EUR", monthly_volume=None,
    )

    assert [(c.trigger, c.departments) for c in found] == [(config.TRIGGER_RETURNS_SLA, ["warehouse"])]
    assert "24 horas" in found[0].evidence[0]


def test_currency_mismatch_by_country_and_between_sections():
    found = conflicts.detect_conflicts(sections(warehouse=EUR_TABLE, reverse=USD_TABLE), currency="EUR", monthly_volume=None)
    assert [(c.trigger, c.departments) for c in found] == [(config.TRIGGER_CURRENCY, ["reverse"])]

    unknown = conflicts.detect_conflicts(sections(warehouse=EUR_TABLE, lastmile=USD_TABLE), currency=None, monthly_volume=None)
    assert unknown[0].trigger == config.TRIGGER_CURRENCY and unknown[0].data["expected"] is None

    assert conflicts.detect_conflicts(sections(warehouse=EUR_TABLE, reverse=EUR_TABLE), currency="EUR", monthly_volume=None) == []


# --------------------------------------------------------------------------- #
# Árbitro fijo
# --------------------------------------------------------------------------- #
def returns_conflict(department_id):
    return conflicts.detect_conflicts(
        sections(**{department_id: EUR_TABLE + "\n- Las devoluciones se procesan en el mismo día."}), currency="EUR",
        monthly_volume=None,
    )


def test_sofia_ramos_forces_changes_on_her_own_section_and_miguel_torres_on_another():
    own = arbiter.arbitrate(returns_conflict("reverse"), round_number=1)
    other = arbiter.arbitrate(returns_conflict("warehouse"), round_number=1)

    assert own.decisions[0]["arbiter"] == "Sofía Ramos" and own.decisions[0]["action"] == "request_changes"
    assert other.decisions[0]["arbiter"] == "Miguel Torres"
    assert own.decisions[0]["mode"] == "rule" and own.decisions[0]["rule"] == config.RESOLUTION_RULES[config.TRIGGER_RETURNS_SLA]
    assert "72 horas" in own.forced["reverse"][0]["feedback"]


def test_volume_rule_caps_the_proposal_to_the_warehouse_capacity():
    found = conflicts.detect_conflicts(
        sections(warehouse=USD_TABLE + "\nCon 30.000 pedidos al mes.", lastmile=USD_TABLE + "\nCon 30.000 pedidos al mes."),
        currency="USD", monthly_volume=30000,
    )

    result = arbiter.arbitrate(found, round_number=1)

    capacity = config.WAREHOUSE_MONTHLY_CAPACITY["USD"]
    assert result.decisions[0]["arbiter"] == "Miguel Torres"
    assert set(result.forced) == {"warehouse", "lastmile"}  # un único volumen en todo el documento
    assert result.overrides == {"warehouse": {"monthly_volume": capacity}, "lastmile": {"monthly_volume": capacity}}


def test_after_the_round_limit_the_arbiter_rejects_and_without_country_it_blocks():
    limited = arbiter.arbitrate(returns_conflict("reverse"), round_number=config.MAX_ARBITRATION_ROUNDS + 1)
    blocked = arbiter.arbitrate(
        conflicts.detect_conflicts(sections(warehouse=EUR_TABLE, lastmile=USD_TABLE), currency=None, monthly_volume=None),
        round_number=1,
    )

    assert limited.forced == {} and "reverse" in limited.rejected
    assert limited.decisions[0]["action"] == "reject"
    assert blocked.forced == {} and blocked.blocked and blocked.decisions[0]["action"] == "blocked"


# --------------------------------------------------------------------------- #
# Respuesta humana (se valida antes del resume)
# --------------------------------------------------------------------------- #
def test_only_the_named_responsible_can_decide_on_a_section():
    assert validate_decision({"decision": "approve", "approver": "Ana Whitfield"}, "warehouse").decision == "approve"
    with pytest.raises(ValidationError, match="solo Ana Whitfield"):
        validate_decision({"decision": "approve", "approver": "Carlos Vega"}, "warehouse")


@pytest.mark.parametrize(
    "payload",
    [
        {"decision": "reject", "approver": "Sofía Ramos", "comment": ""},
        {"decision": "request_changes", "approver": "Sofía Ramos", "comment": "corto"},
        {"decision": "maybe", "approver": "Sofía Ramos"},
        {"decision": "approve", "approver": "Sofía Ramos", "role": "admin"},
        "approve",
    ],
)
def test_rejecting_or_requesting_changes_needs_a_reason_and_unknown_shapes_are_refused(payload):
    with pytest.raises((ValidationError, ValueError)):
        validate_decision(payload, "reverse")


# --------------------------------------------------------------------------- #
# Documento final y traza
# --------------------------------------------------------------------------- #
def signoff(department_id, approver, status="aprobada"):
    return {
        "department_id": department_id, "approval_status": status, "approver": approver,
        "decided_at": "2026-11-26T10:30:00+00:00", "approval_requested_at": "2026-11-26T10:00:00+00:00",
        "rounds": 1, "draft_content": f"## Propuesta económica — {department_id}\n\n{EUR_TABLE}", "comment": "",
    }


def test_the_final_document_consolidates_approved_sections_in_briefing_order():
    final = document.build_final_document(
        ticket_id=7, rfp_id="rfp-7", client={"name": "ModaViva", "country": "Spain"}, currency="EUR",
        signoffs={"reverse": signoff("reverse", "Sofía Ramos"), "warehouse": signoff("warehouse", "Ana Whitfield")},
        arbitrations=[], created_at="2026-11-26T09:00:00+00:00",
    )

    assert set(final) >= {"ticket_id", "sections", "currency", "generated_at", "markdown"}  # FinalDocument §2.3
    assert [s["department_id"] for s in final["sections"]] == ["warehouse", "reverse"]
    assert final["metrics"]["approval_minutes"] == {"warehouse": 30.0, "reverse": 30.0}  # KPI §3
    assert final["markdown"].index("— warehouse") < final["markdown"].index("— reverse")
    assert "Aprobada por **Sofía Ramos**" in final["markdown"]


def test_there_is_no_final_document_with_a_rejected_section():
    with pytest.raises(ValueError, match="no está aprobada"):
        document.build_final_document(
            ticket_id=7, rfp_id=None, client={}, currency="EUR", arbitrations=[],
            signoffs={"warehouse": signoff("warehouse", "Ana Whitfield"), "reverse": signoff("reverse", "Sofía Ramos", "rechazada")},
        )


def test_traced_records_agent_input_output_and_timestamps_and_marks_interrupts():
    sink = trace.ListSink()

    def node(state):
        return {"round": state["round"] + 1}

    def paused(state):
        class GraphInterrupt(Exception):
            interrupts = ()
        raise GraphInterrupt()

    wrapped = trace.traced("humano: Ana Whitfield", "human_approval", node, graph="g", sink=sink,
                           thread_id=lambda s: f"rfp-{s['ticket_id']}:{s['department_id']}", input_keys=("round",))
    update = wrapped({"ticket_id": 3, "department_id": "warehouse", "round": 0})
    with pytest.raises(Exception):
        trace.traced("x", "human_approval", paused, graph="g", sink=sink, thread_id=lambda s: "t")({"ticket_id": 3})

    entry = update["trace"][0]
    assert entry["agent"] == "humano: Ana Whitfield" and entry["thread_id"] == "rfp-3:warehouse"
    assert entry["input"] == {"round": 0} and entry["output"] == {"round": 1}
    assert entry["started_at"] <= entry["finished_at"] and entry["status"] == "ok"
    assert [e["status"] for e in sink.entries] == ["ok", "interrupted"]


def test_thread_ids_are_namespaced_by_ticket_and_department():
    assert config.ticket_thread_id(12) == "rfp-12"
    assert config.department_thread_id(12, "lastmile") == "rfp-12:lastmile"
    assert config.department_thread_id(12, "lastmile") != config.department_thread_id(13, "lastmile")
