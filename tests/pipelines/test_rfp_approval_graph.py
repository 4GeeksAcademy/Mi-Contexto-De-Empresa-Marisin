"""Grafos de la Parte 3 con LangGraph real: interrupt + checkpointer + resume, ramas en paralelo y arbitraje.

Cubre: la rama se pausa antes de la aprobación con su estado en el checkpointer
y se reanuda en el mismo nodo (sin reiniciar); aprobar B mientras A sigue
interrumpida (aserción sobre el estado de los hilos y sobre la traza); pedir
cambios vuelve al generador de la Parte 2; límite de rondas; arbitraje con el
árbitro fijo y su límite; documento final solo con todo aprobado; tickets
concurrentes sin compartir checkpoint; reanudar tras «reiniciar» con SQLite.
"""

import pytest

pytest.importorskip("langgraph")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from data.pipelines.rfp_intake.approval import config, nodes  # noqa: E402
from data.pipelines.rfp_intake.approval.runner import ApprovalService, InvalidDecision  # noqa: E402
from data.pipelines.rfp_intake.store import InMemoryRfpStore, NotApprovable  # noqa: E402
from rfp_helpers import FORMAL, INFORMAL, approve, offline_llm, ticket_ready_for_approval  # noqa: E402


@pytest.fixture
def store():
    return InMemoryRfpStore()


@pytest.fixture
def service(store):
    return ApprovalService(store, llm=offline_llm, checkpointer=InMemorySaver())


def ticket(store, fixture=INFORMAL):
    return ticket_ready_for_approval(store, fixture)


def section(store, ticket_id, department_id):
    return next(s for s in store.get_ticket(ticket_id)["sections"] if s["department_id"] == department_id)


def part3_trace(store, ticket_id):
    return [e for e in store.list_trace(ticket_id) if e["graph"] in (config.GRAPH_NAME, config.DEPARTMENT_GRAPH_NAME)]


def test_the_graphs_are_dedicated_and_have_the_hitl_and_closing_nodes(service):
    department_nodes = set(service.department_graph.get_graph().nodes)
    ticket_nodes = set(service.ticket_graph.get_graph().nodes)

    assert set(nodes.DEPARTMENT_NODES) <= department_nodes
    assert set(nodes.TICKET_NODES) <= ticket_nodes
    assert not ticket_nodes & {"generate", "judge", "classify_document", "retrieve"}


def test_each_branch_pauses_before_approval_with_its_state_checkpointed(store, service):
    ticket_id = ticket(store)

    summary = service.start(ticket_id)

    assert summary["status"] == config.STATUS_AWAITING
    assert summary["ticket_waiting"] is True and summary["pending"] == ["warehouse", "lastmile"]
    for department_id in ("warehouse", "lastmile"):
        snapshot = service.branch_snapshot(ticket_id, department_id)
        assert snapshot.next == (nodes.NODE_HUMAN,)
        request = snapshot.tasks[0].interrupts[0].value
        assert request["responsible"] == section(store, ticket_id, department_id)["responsible"]
        assert request["department_id"] == department_id and request["max_rounds"] == config.MAX_APPROVAL_ROUNDS
        assert section(store, ticket_id, department_id)["approval_status"] == config.APPROVAL_PENDING
    assert store.get_final_document(ticket_id) is None


def test_resume_continues_at_the_interrupted_node_without_restarting(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)
    before = [e["node"] for e in part3_trace(store, ticket_id) if e["department_id"] == "lastmile"]

    approve(service, ticket_id, "lastmile")

    after = [e["node"] for e in part3_trace(store, ticket_id) if e["department_id"] == "lastmile"][len(before):]
    assert before == [nodes.NODE_PREPARE, nodes.NODE_REQUEST, nodes.NODE_HUMAN]
    assert after == [nodes.NODE_HUMAN, nodes.NODE_SIGNOFF]  # ni prepare_review ni request_approval otra vez
    assert service.branch_snapshot(ticket_id, "lastmile").next == ()


def test_approving_B_while_A_is_still_interrupted(store, service):
    """Ramas paralelas reales: lastmile termina mientras warehouse sigue en pausa en su interrupt."""
    ticket_id = ticket(store)
    service.start(ticket_id)

    summary = approve(service, ticket_id, "lastmile")

    assert summary["branches"]["lastmile"] == {"thread_id": f"rfp-{ticket_id}:lastmile", "waiting": False,
                                               "approval_status": config.APPROVAL_APPROVED}
    assert summary["branches"]["warehouse"]["waiting"] is True
    assert service.branch_snapshot(ticket_id, "warehouse").next == (nodes.NODE_HUMAN,)
    assert summary["pending"] == ["warehouse"] and summary["status"] == config.STATUS_AWAITING
    assert section(store, ticket_id, "lastmile")["approver"] == "Carlos Vega"
    assert section(store, ticket_id, "lastmile")["approved_at"] is not None
    assert store.get_final_document(ticket_id) is None
    # En la traza: la decisión de lastmile ocurre después de que warehouse se pausó y sin que warehouse avance.
    events = part3_trace(store, ticket_id)
    paused = max(i for i, e in enumerate(events) if e["department_id"] == "warehouse" and e["status"] == "interrupted")
    decided = next(i for i, e in enumerate(events) if e["department_id"] == "lastmile" and e["node"] == nodes.NODE_SIGNOFF)
    assert paused < decided
    assert not [e for e in events[paused + 1:] if e["department_id"] == "warehouse"]


def test_the_final_document_is_generated_only_when_every_section_is_approved(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)
    approve(service, ticket_id, "warehouse")
    assert store.get_ticket(ticket_id)["status"] == config.STATUS_AWAITING

    summary = approve(service, ticket_id, "lastmile")

    document = store.get_final_document(ticket_id)
    assert summary["status"] == config.STATUS_DONE and summary["stage"] == config.STAGE_DONE
    assert [s["department_id"] for s in document["sections"]] == ["warehouse", "lastmile"]
    assert document["currency"] == "USD" and document["ticket_id"] == ticket_id
    assert [s["approver"] for s in document["sections"]] == ["Ana Whitfield", "Carlos Vega"]
    assert part3_trace(store, ticket_id)[-1]["node"] == nodes.NODE_CLOSE


def test_request_changes_goes_back_to_the_part2_generator_and_pauses_again(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)

    summary = approve(service, ticket_id, "warehouse", "request_changes", "Indica el plazo de onboarding al principio.")

    branch = service.branch_snapshot(ticket_id, "warehouse")
    assert branch.next == (nodes.NODE_HUMAN,) and summary["branches"]["warehouse"]["waiting"] is True
    assert branch.values["round"] == 1 and branch.values["revisions"][0]["requested_by"] == ["Ana Whitfield"]
    assert "Indica el plazo de onboarding" in branch.values["revisions"][0]["feedback"]
    saved = section(store, ticket_id, "warehouse")
    assert saved["approval_status"] == config.APPROVAL_PENDING and saved["approval_round"] == 1
    assert store.get_ticket(ticket_id)["stage"] == config.STAGE_AWAITING  # no se queda en revisando_secciones
    requested = saved["approval_history"][0]  # la petición de cambios también queda en el historial
    assert (requested["decision"], requested["approver"], requested["round"]) == ("request_changes", "Ana Whitfield", 1)
    assert "Indica el plazo de onboarding" in requested["comment"]
    assert any(entry.get("phase") == "approval" for entry in saved["evaluation_history"])  # reevaluada en la Parte 3
    nodes_run = [e["node"] for e in part3_trace(store, ticket_id) if e["department_id"] == "warehouse"]
    assert nodes_run[-4:] == [nodes.NODE_HUMAN, nodes.NODE_REVISE, nodes.NODE_REQUEST, nodes.NODE_HUMAN]


def test_the_round_limit_rejects_the_section_and_blocks_the_final_document(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)
    for _ in range(config.MAX_APPROVAL_ROUNDS):
        approve(service, ticket_id, "lastmile", "request_changes", "Sigue sin convencerme el texto.")
    assert service.branch_snapshot(ticket_id, "lastmile").values["round"] == config.MAX_APPROVAL_ROUNDS

    summary = approve(service, ticket_id, "lastmile", "request_changes", "Una ronda más, por favor.")

    assert section(store, ticket_id, "lastmile")["approval_status"] == config.APPROVAL_REJECTED
    assert "Límite de 3 rondas" in section(store, ticket_id, "lastmile")["approval_comment"]
    assert summary["stage"] == config.STAGE_REJECTED and store.get_final_document(ticket_id) is None
    with pytest.raises(NotApprovable, match="rechazada"):
        approve(service, ticket_id, "warehouse")


def test_a_human_rejection_needs_a_new_execution(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)

    approve(service, ticket_id, "warehouse", "reject", "El cliente pidió Chicago, no Los Ángeles.")

    saved = store.get_ticket(ticket_id)
    assert saved["status"] == config.STATUS_AWAITING and saved["stage"] == config.STAGE_REJECTED
    assert section(store, ticket_id, "warehouse")["approval_status"] == config.APPROVAL_REJECTED
    assert store.claim_for_drafting(ticket_id, force=True)["status"] == "generando_borrador"  # relanzar la Parte 2


def test_an_invalid_decision_never_reaches_the_graph(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)
    before = len(store.list_trace(ticket_id))

    with pytest.raises(InvalidDecision, match="solo Ana Whitfield"):
        service.decide(ticket_id, "warehouse", {"decision": "approve", "approver": "Carlos Vega"})
    with pytest.raises(InvalidDecision):
        service.decide(ticket_id, "warehouse", {"decision": "reject", "approver": "Ana Whitfield"})
    with pytest.raises(NotApprovable):
        service.decide(ticket_id, "reverse", {"decision": "approve", "approver": "Sofía Ramos"})  # no participa

    assert len(store.list_trace(ticket_id)) == before
    assert service.branch_waiting(ticket_id, "warehouse")


def test_a_second_decision_on_the_same_branch_is_refused(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)
    approve(service, ticket_id, "lastmile")

    with pytest.raises(NotApprovable, match="no está esperando"):
        approve(service, ticket_id, "lastmile")


def test_returns_breach_is_arbitrated_by_the_fixed_arbiter_before_asking_for_approval(store):
    from data.pipelines.rfp_intake.approval.e2e import BREACH_LINE

    ticket_id = ticket(store, FORMAL)
    output = store.get_ticket(ticket_id)["drafting_handoff"]
    reverse = next(s for s in output["sections"] if s["department_id"] == "reverse")
    reverse["draft_content"] += BREACH_LINE + "\n"  # un borrador provisional que Ventas no debería enviar
    store.complete_drafting(ticket_id, output)
    service = ApprovalService(store, llm=offline_llm, checkpointer=InMemorySaver())

    service.start(ticket_id)

    state = service.ticket_snapshot(ticket_id).values
    decision = state["arbitrations"][0]
    assert (decision["trigger"], decision["arbiter"], decision["action"]) == ("returns-sla-breach", "Sofía Ramos", "request_changes")
    branch = service.branch_snapshot(ticket_id, "reverse").values
    assert branch["round"] == 1 and "24 horas" not in branch["section"]["draft_content"]
    assert branch["arbitration_notes"] and service.pending_requests(ticket_id)[1]["arbitration_notes"]
    approve(service, ticket_id, "warehouse")
    approve(service, ticket_id, "reverse")
    assert store.get_final_document(ticket_id)["arbitrations"][0]["arbiter"] == "Sofía Ramos"


def test_concurrent_tickets_do_not_share_checkpoints(store, service):
    first, second = ticket(store), ticket(store)

    service.start(first)
    service.start(second)
    approve(service, first, "lastmile")

    assert service.branch_snapshot(first, "lastmile").next == ()
    assert service.branch_snapshot(second, "lastmile").next == (nodes.NODE_HUMAN,)
    assert service.summary(second)["pending"] == ["warehouse", "lastmile"]


def test_starting_again_resets_the_threads_instead_of_inheriting_them(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)
    approve(service, ticket_id, "lastmile")

    summary = service.start(ticket_id, force=True)

    assert summary["pending"] == ["warehouse", "lastmile"]
    assert section(store, ticket_id, "lastmile")["approval_status"] == config.APPROVAL_PENDING


def test_a_branch_resumes_from_sqlite_after_a_restart(store, tmp_path):
    pytest.importorskip("langgraph.checkpoint.sqlite")
    from data.pipelines.rfp_intake.approval.checkpoint import make_checkpointer

    path = tmp_path / "rfp_approval.sqlite"
    ticket_id = ticket(store)
    ApprovalService(store, llm=offline_llm, checkpointer=make_checkpointer("sqlite", path)).start(ticket_id)

    restarted = ApprovalService(store, llm=offline_llm, checkpointer=make_checkpointer("sqlite", path))  # proceso nuevo
    assert restarted.branch_waiting(ticket_id, "warehouse") and restarted.ticket_waiting(ticket_id)
    approve(restarted, ticket_id, "warehouse")
    summary = approve(ApprovalService(store, llm=offline_llm, checkpointer=make_checkpointer("sqlite", path)),
                      ticket_id, "lastmile")

    assert summary["status"] == config.STATUS_DONE
    assert path.exists()


def test_every_node_execution_is_traced_with_agent_input_output_and_timestamp(store, service):
    ticket_id = ticket(store)
    service.start(ticket_id)
    approve(service, ticket_id, "warehouse")
    approve(service, ticket_id, "lastmile")

    events = store.list_trace(ticket_id)

    assert {e["graph"] for e in events} == {"rfp_drafting", config.GRAPH_NAME, config.DEPARTMENT_GRAPH_NAME}
    for event in events:
        assert event["agent"] and event["node"] and event["finished_at"]
        assert isinstance(event["input"], dict) and isinstance(event["output"], dict)
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    humans = {e["agent"] for e in events if e["node"] == nodes.NODE_HUMAN}
    assert humans == {"humano: Ana Whitfield", "humano: Carlos Vega"}
    state_trace = service.branch_snapshot(ticket_id, "warehouse").values["trace"]
    assert [e["node"] for e in state_trace] == [nodes.NODE_PREPARE, nodes.NODE_REQUEST, nodes.NODE_HUMAN, nodes.NODE_SIGNOFF]
