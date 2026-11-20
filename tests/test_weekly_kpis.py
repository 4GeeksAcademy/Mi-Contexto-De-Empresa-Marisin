"""KPIs del Reporte Semanal de Desempeño por Almacén y Cliente (BRIEFING §2 y §4)."""

from datetime import date

import pandas as pd
import pytest

from data.process import weekly_kpis as kpis


def _event(event_id, event_type, timestamp, warehouse="los_angeles", client_id="ecowear_usa", quantity=None, **extra):
    row = {
        "id": f"row-{event_id}-{timestamp}",
        "timestamp": timestamp,
        "event_type": event_type,
        "event_id": event_id,
        "warehouse": warehouse,
        "client_id": client_id,
        "quantity": None if quantity is None else str(quantity),
        "user_id": "u_operator",
        "request_id": f"req-{event_id}",
    }
    row.update(extra)
    return row


@pytest.fixture
def week_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _event("e1", kpis.INBOUND, "2026-11-16T09:00:00+00:00", quantity=20),
            _event("e2", kpis.INBOUND, "2026-11-17T09:00:00+00:00", quantity=5),
            _event("e3", kpis.OUTBOUND, "2026-11-17T10:00:00+00:00"),
            _event("e4", kpis.OUTBOUND, "2026-11-18T10:00:00+00:00"),
            _event("e5", kpis.OUTBOUND, "2026-11-18T11:00:00+00:00"),
            _event("e6", kpis.OUTBOUND, "2026-11-19T11:00:00+00:00"),
            _event("e7", kpis.STOCKOUT, "2026-11-19T11:00:01+00:00", quantity=49),
            _event("e8", kpis.DISCREPANCY, "2026-11-20T08:00:00+00:00", quantity=-2),
            _event("z1", kpis.OUTBOUND, "2026-11-18T10:00:00+00:00", warehouse="zaragoza", client_id="hydrolife"),
        ]
    )


def test_kpis_match_briefing_definitions(week_events):
    result = kpis.transform_events(week_events)
    rows = {(row["warehouse"], row["client_id"]): row for row in kpis.kpis_to_records(result.kpis)}

    la = rows[("los_angeles", "ecowear_usa")]
    assert la["week_start"] == date(2026, 11, 16)
    assert la["inbound_units_count"] == 25  # suma de cantidades, no conteo de órdenes
    assert la["outbound_orders_count"] == 4
    assert la["stockout_events_count"] == 1
    assert la["discrepancy_events_count"] == 1
    assert la["discrepancy_rate"] == pytest.approx(0.25)

    zaragoza = rows[("zaragoza", "hydrolife")]
    assert zaragoza["outbound_orders_count"] == 1
    assert zaragoza["inbound_units_count"] == 0


def test_output_columns_are_the_briefing_grain_and_kpis(week_events):
    result = kpis.transform_events(week_events)
    assert tuple(result.kpis.columns) == (
        "warehouse",
        "client_id",
        "week_start",
        "inbound_units_count",
        "outbound_orders_count",
        "stockout_events_count",
        "discrepancy_events_count",
        "discrepancy_rate",
    )


def test_discrepancy_rate_is_zero_without_outbound_orders():
    events = pd.DataFrame([_event("d1", kpis.DISCREPANCY, "2026-11-16T08:00:00+00:00", quantity=3)])
    row = kpis.kpis_to_records(kpis.transform_events(events).kpis)[0]
    assert row["discrepancy_events_count"] == 1
    assert row["outbound_orders_count"] == 0
    assert row["discrepancy_rate"] == 0.0


def test_duplicate_event_id_is_counted_once():
    events = pd.DataFrame(
        [
            _event("dup", kpis.OUTBOUND, "2026-11-17T10:00:00.000+00:00"),
            _event("dup", kpis.OUTBOUND, "2026-11-17T10:00:00.300+00:00"),
        ]
    )
    result = kpis.transform_events(events)
    assert result.stats["duplicates_dropped"] == 1
    assert kpis.kpis_to_records(result.kpis)[0]["outbound_orders_count"] == 1


def test_iso_week_boundary_is_monday_utc():
    events = pd.DataFrame(
        [
            _event("sun", kpis.STOCKOUT, "2026-11-22T23:59:59+00:00", quantity=10),
            _event("mon", kpis.STOCKOUT, "2026-11-23T00:00:00+00:00", quantity=10),
        ]
    )
    weeks = sorted(row["week_start"] for row in kpis.kpis_to_records(kpis.transform_events(events).kpis))
    assert weeks == [date(2026, 11, 16), date(2026, 11, 23)]


def test_verification_events_are_excluded():
    events = pd.DataFrame(
        [
            _event("c1", kpis.INBOUND, "2026-11-19T07:00:01+00:00", client_id="nova_beauty", quantity=12, user_id="curl_verification"),
            _event("r1", kpis.INBOUND, "2026-11-19T07:12:00+00:00", quantity=20),
        ]
    )
    result = kpis.transform_events(events, excluded_user_ids=("curl_verification",))
    assert result.stats["events_excluded"] == 1
    assert [row["client_id"] for row in kpis.kpis_to_records(result.kpis)] == ["ecowear_usa"]


def test_invalid_rows_are_rejected_with_reason():
    events = pd.DataFrame(
        [
            _event("w1", kpis.OUTBOUND, "2026-11-17T10:00:00+00:00", warehouse="madrid"),
            _event("c1", kpis.OUTBOUND, "2026-11-17T10:00:00+00:00", client_id="EcoWear USA"),
            _event("q1", kpis.INBOUND, "2026-11-17T10:00:00+00:00", quantity=0),
            _event(None, kpis.OUTBOUND, "2026-11-17T10:00:00+00:00"),
        ]
    )
    result = kpis.transform_events(events)
    assert result.kpis.empty
    assert result.stats["rejected_by_reason"] == {
        "invalid_warehouse": 1,
        "invalid_client_id": 1,
        "invalid_quantity": 1,
        "missing_event_id": 1,
    }


def test_empty_extraction_returns_empty_frame_with_columns():
    result = kpis.transform_events(pd.DataFrame(columns=list(kpis.RAW_COLUMNS)))
    assert result.kpis.empty
    assert tuple(result.kpis.columns) == kpis.OUTPUT_COLUMNS
    assert result.stats["events_extracted"] == 0


def test_transform_is_deterministic_and_order_independent(week_events):
    first = kpis.transform_events(week_events).kpis
    second = kpis.transform_events(week_events.sample(frac=1, random_state=7)).kpis
    pd.testing.assert_frame_equal(first, second)


def test_cache_key_depends_on_data_and_config(week_events):
    key = kpis.transform_cache_key(week_events, ("curl_verification",))
    assert key == kpis.transform_cache_key(week_events.iloc[::-1], ("curl_verification",))
    late_event = pd.concat(
        [week_events, pd.DataFrame([_event("late", kpis.OUTBOUND, "2026-11-20T12:00:00+00:00")])]
    )
    assert key != kpis.transform_cache_key(late_event, ("curl_verification",))
    assert key != kpis.transform_cache_key(week_events, ())


def test_resolve_weeks_uses_closed_weeks_by_default():
    assert kpis.resolve_weeks(date(2026, 11, 19), lookback_weeks=4) == [
        date(2026, 10, 19),
        date(2026, 10, 26),
        date(2026, 11, 2),
        date(2026, 11, 9),
    ]
    assert kpis.resolve_weeks(date(2026, 11, 19), week_start=date(2026, 11, 16)) == [date(2026, 11, 16)]
    with pytest.raises(ValueError):
        kpis.resolve_weeks(date(2026, 11, 19), week_start=date(2026, 11, 18))
    assert kpis.window_bounds([date(2026, 11, 9), date(2026, 11, 16)]) == (date(2026, 11, 9), date(2026, 11, 23))


def test_validate_kpis_detects_contract_violations(week_events):
    result = kpis.transform_events(week_events)
    assert kpis.validate_kpis(result.kpis, [date(2026, 11, 16)]) == []
    broken = pd.concat([result.kpis, result.kpis.iloc[[0]]])
    assert kpis.validate_kpis(broken, [date(2026, 11, 16)])
    assert kpis.validate_kpis(result.kpis, [date(2026, 11, 23)])


def test_capture_coverage_compares_events_with_domain_orders():
    domain = pd.DataFrame(
        [
            {"kind": "inbound", "warehouse": "Los Angeles", "orders": 4},
            {"kind": "outbound", "warehouse": "Zaragoza", "orders": 2},
        ]
    )
    coverage, warnings = kpis.capture_coverage(
        {"los_angeles": {"inbound": 2, "outbound": 0}, "zaragoza": {"inbound": 0, "outbound": 0}},
        domain,
        warning_threshold=0.9,
    )
    assert coverage["los_angeles"]["inbound"] == {"events": 2, "orders": 4, "coverage": 0.5}
    assert "low_capture_coverage:los_angeles:inbound" in warnings
    assert "capture_silence:zaragoza:outbound" in warnings
