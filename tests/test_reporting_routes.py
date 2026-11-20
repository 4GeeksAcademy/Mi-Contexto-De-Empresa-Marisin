"""Endpoints de `services/reporting/` (BRIEFING de data pipelines §6)."""

from datetime import date, datetime, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from data.pipelines import triggers
from data.pipelines.config import PipelineConfig
from services.api import database
from services.api.main import app
from services.api.security import get_current_user
from services.reporting import router as reporting_router


RUN_ID = UUID("6a1f3c52-8e0d-4d7a-9c1b-2f3e4d5a6b7c")
WEEK = {
    "week_start": date(2026, 11, 16),
    "entries": [
        {
            "warehouse": "los_angeles",
            "client_id": "ecowear_usa",
            "inbound_units_count": 20,
            "outbound_orders_count": 1,
            "stockout_events_count": 0,
            "discrepancy_events_count": 0,
            "discrepancy_rate": 0.0,
        }
    ],
}
NOW = datetime(2026, 11, 23, 5, 0, tzinfo=timezone.utc)
LATEST_RUN = {
    "run_id": RUN_ID,
    "pipeline_name": "weekly_warehouse_client_performance",
    "trigger": "scheduled",
    "triggered_by": None,
    "prefect_flow_run_id": None,
    "status": "completed",
    "last_completed_phase": "load",
    "window_start": date(2026, 10, 26),
    "window_end": date(2026, 11, 23),
    "started_at": NOW,
    "heartbeat_at": NOW,
    "finished_at": NOW,
    "loaded_at": NOW,
    "duration_ms": 1830,
    "records_processed": 9,
    "events_extracted": 9,
    "duplicates_dropped": 1,
    "events_excluded": 1,
    "events_rejected": 0,
    "events_by_type": {"inbound_order_created": 1},
    "rows_inserted": 1,
    "rows_updated": 0,
    "rows_unchanged": 0,
    "rows_deleted": 0,
    "source_max_timestamp": NOW,
    "capture_coverage": {},
    "warnings": [],
    "error_type": None,
    "error_message": None,
}


@pytest.fixture
def user():
    return {"id": 1, "is_active": True, "role": "admin"}


@pytest.fixture
def client(monkeypatch, user):
    monkeypatch.setattr(database, "engine", object())
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_kpis_endpoint_matches_briefing_contract(client, monkeypatch):
    calls = []

    def fake_week(engine, week_start):
        calls.append(week_start)
        return WEEK

    monkeypatch.setattr(reporting_router.queries, "get_weekly_performance", fake_week)
    response = client.get("/reporting/weekly-warehouse-client-performance")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"week_start", "entries"}
    assert body["week_start"] == "2026-11-16"
    assert set(body["entries"][0]) == {
        "warehouse",
        "client_id",
        "inbound_units_count",
        "outbound_orders_count",
        "stockout_events_count",
        "discrepancy_events_count",
        "discrepancy_rate",
    }
    assert calls == [None]  # sin week_start: la semana calculada más reciente


def test_kpis_endpoint_accepts_explicit_monday(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        reporting_router.queries,
        "get_weekly_performance",
        lambda engine, week_start: calls.append(week_start) or WEEK,
    )
    assert client.get("/reporting/weekly-warehouse-client-performance?week_start=2026-11-16").status_code == 200
    assert calls == [date(2026, 11, 16)]


def test_kpis_endpoint_rejects_non_monday(client):
    response = client.get("/reporting/weekly-warehouse-client-performance?week_start=2026-11-18")
    assert response.status_code == 422


def test_kpis_endpoint_404_when_week_not_computed(client, monkeypatch):
    monkeypatch.setattr(reporting_router.queries, "get_weekly_performance", lambda engine, week_start: None)
    assert client.get("/reporting/weekly-warehouse-client-performance").status_code == 404


def test_kpis_endpoint_503_on_database_error(client, monkeypatch):
    def broken(engine, week_start):
        raise OperationalError("select", {}, Exception("timeout"))

    monkeypatch.setattr(reporting_router.queries, "get_weekly_performance", broken)
    assert client.get("/reporting/weekly-warehouse-client-performance").status_code == 503


def test_latest_run_returns_metadata(client, monkeypatch):
    monkeypatch.setattr(reporting_router.queries, "get_latest_pipeline_run", lambda engine: LATEST_RUN)
    response = client.get("/reporting/pipeline-runs/latest")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["started_at"] and body["finished_at"]
    assert body["records_processed"] == 9
    assert body["error_message"] is None


def test_latest_run_404_when_never_ran(client, monkeypatch):
    monkeypatch.setattr(reporting_router.queries, "get_latest_pipeline_run", lambda engine: None)
    assert client.get("/reporting/pipeline-runs/latest").status_code == 404


def test_manual_trigger_returns_202_and_uses_pipeline_trigger(client, monkeypatch):
    calls = []

    def fake_trigger(engine, *, week_start, triggered_by):
        calls.append((week_start, triggered_by))
        return triggers.ManualRun(run_id=RUN_ID, status="pending", week_start=week_start)

    monkeypatch.setattr(reporting_router.triggers, "trigger_manual_run", fake_trigger)
    response = client.post("/reporting/pipeline-runs", json={"week_start": "2026-11-16"})

    assert response.status_code == 202
    assert response.json() == {"run_id": str(RUN_ID), "status": "pending", "week_start": "2026-11-16"}
    assert calls == [(date(2026, 11, 16), "1")]


def test_manual_trigger_without_body(client, monkeypatch):
    monkeypatch.setattr(
        reporting_router.triggers,
        "trigger_manual_run",
        lambda engine, *, week_start, triggered_by: triggers.ManualRun(RUN_ID, "pending", week_start),
    )
    response = client.post("/reporting/pipeline-runs")
    assert response.status_code == 202
    assert response.json()["week_start"] is None


def test_manual_trigger_409_when_a_run_is_active(client, monkeypatch):
    def busy(engine, *, week_start, triggered_by):
        raise triggers.PipelineRunAlreadyActiveError(RUN_ID)

    monkeypatch.setattr(reporting_router.triggers, "trigger_manual_run", busy)
    response = client.post("/reporting/pipeline-runs")
    assert response.status_code == 409
    assert response.json()["detail"]["active_run_id"] == str(RUN_ID)


def test_manual_trigger_requires_admin_or_manager(client, user):
    user["role"] = "user"
    assert client.post("/reporting/pipeline-runs").status_code == 403


def test_reporting_requires_session():
    app.dependency_overrides.pop(get_current_user, None)
    plain = TestClient(app)
    assert plain.get("/reporting/weekly-warehouse-client-performance").status_code == 401
    assert plain.get("/reporting/pipeline-runs/latest").status_code == 401
    assert plain.post("/reporting/pipeline-runs").status_code == 401


def test_trigger_manual_run_checks_active_run_before_starting(monkeypatch):
    started = []
    monkeypatch.setattr(triggers, "load_config", PipelineConfig)
    monkeypatch.setattr(triggers.runs, "find_active_run", lambda engine, stale_minutes: RUN_ID)
    monkeypatch.setattr(triggers, "run_flow", lambda *args: started.append(args))
    with pytest.raises(triggers.PipelineRunAlreadyActiveError):
        triggers.trigger_manual_run(object())
    assert started == []
