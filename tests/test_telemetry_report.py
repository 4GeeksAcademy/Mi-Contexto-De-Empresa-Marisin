from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from services.api import database
from services.api.auth import get_current_user
from services.api.cache import telemetry_report_cache
from services.api.main import app
from services.api.routes import telemetry as telemetry_route


METRICS = {
    "events_per_day": [{"date": "2026-11-19", "event_type": "page_viewed", "events": 13}],
    "error_rate_per_day": [
        {
            "date": "2026-11-19",
            "total_events": 46,
            "error_events": 1,
            "warning_events": 1,
            "error_rate": 0.0217,
            "warning_rate": 0.0217,
        }
    ],
    "api_latency_per_day": [
        {
            "date": "2026-11-19",
            "api_endpoint": "/inventory/orders",
            "http_method": "GET",
            "observations": 4,
            "estimated_requests": 12.0,
            "avg_ms": 1300.5,
            "p95_ms": 1799.5,
            "max_ms": 1799.5,
        }
    ],
    "auth_failure_rate": [
        {"date": "2026-11-19", "login_attempts": 2, "login_failures": 1, "failure_rate": 0.5}
    ],
}


@pytest.fixture
def pipeline_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    def fake_build(start_date, end_date, engine):
        calls.append((start_date, end_date, engine))
        return METRICS

    monkeypatch.setattr(telemetry_route.analysis, "build_report_metrics", fake_build)
    monkeypatch.setattr(database, "engine", object())
    telemetry_report_cache.clear()
    yield calls
    telemetry_report_cache.clear()


@pytest.fixture
def client(pipeline_calls):
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_active": True}
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.pop(get_current_user, None)


def test_report_has_period_and_metrics(client):
    response = client.get("/telemetry/report")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"period", "metrics"}
    assert set(body["period"]) == {"from", "to"}
    assert body["metrics"] == METRICS


def test_default_period_is_last_seven_days_in_utc(client, pipeline_calls):
    body = client.get("/telemetry/report").json()

    start = datetime.fromisoformat(body["period"]["from"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(body["period"]["to"].replace("Z", "+00:00"))
    assert end - start == timedelta(days=7)
    assert end.utcoffset() == timedelta(0)
    assert pipeline_calls[0][:2] == (start, end)


def test_explicit_period_is_passed_to_the_pipeline(client, pipeline_calls):
    response = client.get(
        "/telemetry/report",
        params={"start_date": "2026-11-12", "end_date": "2026-11-19T08:00:00Z"},
    )

    assert response.status_code == 200
    assert response.json()["period"] == {
        "from": "2026-11-12T00:00:00Z",
        "to": "2026-11-19T08:00:00Z",
    }
    start, end, _ = pipeline_calls[0]
    assert start.isoformat() == "2026-11-12T00:00:00+00:00"
    assert end.isoformat() == "2026-11-19T08:00:00+00:00"


def test_same_window_within_ttl_is_served_from_cache(client, pipeline_calls):
    params = {"start_date": "2026-11-12T00:00:00Z", "end_date": "2026-11-19T00:00:00Z"}

    first = client.get("/telemetry/report", params=params)
    second = client.get("/telemetry/report", params=params)

    assert first.json() == second.json()
    assert len(pipeline_calls) == 1


def test_default_window_is_cached_between_consecutive_requests(client, pipeline_calls):
    client.get("/telemetry/report")
    client.get("/telemetry/report")

    # Ambas peticiones caen en el mismo minuto salvo en el cambio exacto de minuto.
    assert len(pipeline_calls) in {1, 2}
    assert len(set(call[:2] for call in pipeline_calls)) == len(pipeline_calls)


def test_different_window_recomputes(client, pipeline_calls):
    client.get("/telemetry/report", params={"start_date": "2026-11-12", "end_date": "2026-11-19"})
    client.get("/telemetry/report", params={"start_date": "2026-11-13", "end_date": "2026-11-19"})

    assert len(pipeline_calls) == 2


def test_expired_entry_recomputes(client, pipeline_calls, monkeypatch: pytest.MonkeyPatch):
    params = {"start_date": "2026-11-12", "end_date": "2026-11-19"}
    client.get("/telemetry/report", params=params)

    clock = telemetry_report_cache._clock
    monkeypatch.setattr(telemetry_report_cache, "_clock", lambda: clock() + 61)
    client.get("/telemetry/report", params=params)

    assert len(pipeline_calls) == 2


@pytest.mark.parametrize(
    "params",
    [
        {"start_date": "2026-11-19", "end_date": "2026-11-12"},
        {"start_date": "2026-01-01", "end_date": "2026-11-19"},
        {"start_date": "not-a-date"},
    ],
)
def test_invalid_window_returns_422(client, pipeline_calls, params):
    response = client.get("/telemetry/report", params=params)

    assert response.status_code == 422
    assert pipeline_calls == []


def test_report_requires_authentication(pipeline_calls):
    test_client = TestClient(app)
    response = test_client.get("/telemetry/report")
    test_client.close()

    assert response.status_code == 401
    assert pipeline_calls == []


def test_missing_database_returns_503(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(database, "engine", None)

    response = client.get("/telemetry/report", params={"start_date": "2026-11-10"})

    assert response.status_code == 503
