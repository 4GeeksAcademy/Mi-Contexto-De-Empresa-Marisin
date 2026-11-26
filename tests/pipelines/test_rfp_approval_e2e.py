"""Ruta E2E reproducible: Partes 1 → 3 con aprobaciones humanas simuladas (`resume` programático).

Mismo código que `python scripts/rfp_approval_run.py --e2e <escenario>`: el grafo
`rfp_intake` real sobre la muestra del BRIEFING, el grafo `rfp_drafting` real y
la Parte 3 con un checkpointer SQLite en disco (un servicio nuevo en cada
decisión, como si la API se reiniciara entre una aprobación y la siguiente).
"""

import pytest

pytest.importorskip("langgraph")
pytest.importorskip("langgraph.checkpoint.sqlite")

from data.pipelines.rfp_intake.approval import config  # noqa: E402
from data.pipelines.rfp_intake.approval.e2e import SCENARIOS, run_scenario  # noqa: E402


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_every_e2e_scenario_passes_all_its_checks(scenario, tmp_path):
    result = run_scenario(scenario, tmp_path / f"{scenario}.sqlite")

    failed = [c for c in result["checks"] if not c["passed"]]
    assert failed == [], failed
    assert result["passed"] is True


def test_the_parallel_scenario_keeps_one_ticket_and_consistent_states_across_the_three_parts(tmp_path):
    result = run_scenario("parallel", tmp_path / "parallel.sqlite")

    steps = [(s["step"], s["status"]) for s in result["timeline"]]
    assert [status for _, status in steps] == [
        "analisis_completo", "en_evaluación", config.STATUS_AWAITING, config.STATUS_AWAITING,
        config.STATUS_AWAITING, config.STATUS_DONE,
    ]
    assert result["thread_ids"] == [f"rfp-{result['ticket_id']}", f"rfp-{result['ticket_id']}:warehouse",
                                    f"rfp-{result['ticket_id']}:lastmile"]
    graphs = [e["graph"] for e in result["trace"]]
    assert graphs.index("rfp_intake") < graphs.index("rfp_drafting") < graphs.index(config.GRAPH_NAME)
    document = result["final_document"]
    assert document["client_name"] == "Luna Cosmetics" and document["currency"] == "USD"
    assert {s["approval_status"] for s in result["sections"]} == {config.APPROVAL_APPROVED}
