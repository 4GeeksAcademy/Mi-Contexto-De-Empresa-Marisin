import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from services.telemetry import analysis


START = datetime(2026, 11, 12, tzinfo=timezone.utc)
END = datetime(2026, 11, 19, 8, tzinfo=timezone.utc)

ROWS = [
    # Dos eventos a ambos lados de medianoche UTC: deben caer en días distintos.
    ("2026-11-18T23:59:59.000Z", "page_viewed", "info", {"route": "/inventory"}),
    ("2026-11-19T00:00:01.000Z", "page_viewed", "info", {"route": "/inventory"}),
    (
        "2026-11-19T05:57:56Z",
        "api_latency_recorded",
        "info",
        {"api_endpoint": "/inventory/orders", "http_method": "GET", "duration_ms": 1000, "sample_rate": 1},
    ),
    (
        "2026-11-19T05:57:57Z",
        "api_latency_recorded",
        "info",
        {"api_endpoint": "/inventory/orders", "http_method": "GET", "duration_ms": 100, "sample_rate": 0.2},
    ),
    (
        "2026-11-19T05:57:58Z",
        "api_latency_recorded",
        "info",
        {"api_endpoint": "/inventory/products", "http_method": "GET", "duration_ms": 300, "sample_rate": 0.2},
    ),
    (
        "2026-11-19T05:57:59Z",
        "api_latency_recorded",
        "info",
        {"api_endpoint": None, "http_method": "GET", "duration_ms": 3, "sample_rate": 1},
    ),
    ("2026-11-19T06:00:00Z", "api_request_failed", "error", {}),
    ("2026-11-19T06:01:00Z", "user_login_failed", "warn", {}),
    ("2026-11-19T06:02:00Z", "user_login_succeeded", "info", {}),
    ("2026-11-19T06:03:00Z", "user_login_succeeded", "info", {}),
]


@pytest.fixture
def loads(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Sustituye la carga SQL por los ROWS, aplicando el filtro de event_type pedido."""
    calls: list[dict] = []

    def fake_load(engine, start_date, end_date, columns, event_types=None):
        calls.append(
            {"start": start_date, "end": end_date, "columns": columns, "event_types": event_types}
        )
        events = pd.DataFrame(ROWS, columns=["timestamp", "event_type", "level", "tags"])
        if event_types:
            events = events[events["event_type"].isin(event_types)]
        selected = [column.strip().strip('"') for column in columns.split(",")]
        return events[selected].reset_index(drop=True)

    monkeypatch.setattr(analysis, "_load_events", fake_load)
    return calls


def test_events_per_day_groups_by_utc_date_and_type(loads):
    result = analysis.events_per_day(START, END, engine=None)

    assert {"date": "2026-11-18", "event_type": "page_viewed", "events": 1} in result
    assert {"date": "2026-11-19", "event_type": "page_viewed", "events": 1} in result
    assert result[1] == {"date": "2026-11-19", "event_type": "api_latency_recorded", "events": 4}
    assert loads[0]["event_types"] is None


def test_error_rate_per_day_uses_all_events_of_the_day(loads):
    result = analysis.error_rate_per_day(START, END, engine=None)

    assert result[1] == {
        "date": "2026-11-19",
        "total_events": 9,
        "error_events": 1,
        "warning_events": 1,
        "error_rate": 0.1111,
        "warning_rate": 0.1111,
    }


def test_api_latency_weights_sampled_observations(loads):
    result = analysis.api_latency_per_day(START, END, engine=None)

    assert loads[0]["event_types"] == ("api_latency_recorded",)
    assert result == [
        {
            "date": "2026-11-19",
            "api_endpoint": "/inventory/orders",
            "http_method": "GET",
            "observations": 2,
            "estimated_requests": 6.0,
            "avg_ms": 250.0,
            "p95_ms": 1000.0,
            "max_ms": 1000.0,
        },
        {
            "date": "2026-11-19",
            "api_endpoint": "/inventory/products",
            "http_method": "GET",
            "observations": 1,
            "estimated_requests": 5.0,
            "avg_ms": 300.0,
            "p95_ms": 300.0,
            "max_ms": 300.0,
        },
    ]


def test_auth_failure_rate_loads_both_login_types_in_one_query(loads):
    result = analysis.auth_failure_rate(START, END, engine=None)

    assert len(loads) == 1
    assert loads[0]["event_types"] == ("user_login_failed", "user_login_succeeded")
    assert result == [
        {"date": "2026-11-19", "login_attempts": 3, "login_failures": 1, "failure_rate": 0.3333}
    ]


def test_metrics_pass_the_same_window_to_sql(loads):
    analysis.build_report_metrics(START, END, engine=None)

    assert len(loads) == 4
    assert all(call["start"] == START and call["end"] == END for call in loads)


def test_report_is_json_serializable_and_repeatable(loads):
    first = analysis.build_report_metrics(START, END, engine=None)
    second = analysis.build_report_metrics(START, END, engine=None)

    assert first == second
    json.dumps(first, allow_nan=False)


def test_empty_window_returns_empty_lists(monkeypatch: pytest.MonkeyPatch):
    def empty_load(engine, start_date, end_date, columns, event_types=None):
        selected = [column.strip().strip('"') for column in columns.split(",")]
        return pd.DataFrame(columns=selected)

    monkeypatch.setattr(analysis, "_load_events", empty_load)

    assert analysis.build_report_metrics(START, END, engine=None) == {
        "events_per_day": [],
        "error_rate_per_day": [],
        "api_latency_per_day": [],
        "auth_failure_rate": [],
    }


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeEngine:
    def connect(self):
        return FakeConnection()


def test_load_filters_window_and_event_types_in_sql(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_read_sql(statement, connection, params):
        captured["sql"] = str(statement)
        captured["params"] = params
        return pd.DataFrame()

    monkeypatch.setattr(analysis.pd, "read_sql", fake_read_sql)

    analysis._load_events(
        FakeEngine(), START, END, '"timestamp", event_type', event_types=analysis.AUTH_EVENT_TYPES
    )

    assert 'from public.telemetry_events' in captured["sql"]
    assert '"timestamp" >= :start_date and "timestamp" < :end_date' in captured["sql"]
    assert "event_type in" in captured["sql"]
    assert captured["params"] == {
        "start_date": START,
        "end_date": END,
        "event_types": ["user_login_failed", "user_login_succeeded"],
    }
