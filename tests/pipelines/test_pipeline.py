"""Tests unitarios de los tasks de transformación del Pipeline de Desempeño de Negocio.

Cada test ejecuta la función del task (`task.fn`) de forma aislada, sin base de
datos ni APIs: los eventos son un DataFrame en memoria con la forma exacta de la
extracción de `public.telemetry_events` (PIPELINE_DESIGN.md §3.3), usando los
`event_type` y las propiedades del BRIEFING de TrackFlow.

    python -m pytest tests/pipelines/test_pipeline.py
"""

from datetime import date

import pandas as pd
import pytest

pytest.importorskip("prefect")

from data.pipelines import pipeline  # noqa: E402
from data.process import weekly_kpis  # noqa: E402


WEEK = date(2026, 11, 16)
NEXT_WEEK = date(2026, 11, 23)
_sequence = iter(range(1, 10_000))


def telemetry_event(
    event_type: str,
    timestamp: str,
    *,
    warehouse: str | None = "los_angeles",
    client_id: str | None = "ecowear_usa",
    quantity: object = None,
    event_id: str | None = None,
    user_id: str = "u_operator",
) -> dict:
    """Una fila como la devuelve `extract.extract_events` (tags ya aplanados)."""
    number = next(_sequence)
    return {
        "id": f"00000000-0000-4000-8000-{number:012d}",
        "timestamp": timestamp,
        "event_type": event_type,
        "event_id": event_id if event_id is not None else f"evt-{number}",
        "warehouse": warehouse,
        "client_id": client_id,
        "quantity": None if quantity is None else str(quantity),
        "user_id": user_id,
        "request_id": f"req-{number}",
    }


def prepared(rows: list[dict], excluded_user_ids: tuple[str, ...] = ("curl_verification",)) -> pd.DataFrame:
    """Eventos preparados por el task `prepare_kpi_events`."""
    frame = pd.DataFrame(rows, columns=list(weekly_kpis.RAW_COLUMNS))
    return pipeline.prepare_kpi_events.fn(frame, excluded_user_ids).events


def kpi_value(frame: pd.DataFrame, column: str, warehouse: str, client_id: str, week: date = WEEK) -> int:
    row = frame[
        (frame["warehouse"] == warehouse) & (frame["client_id"] == client_id) & (frame["week_start"] == week)
    ]
    assert len(row) == 1, f"Se esperaba una fila para {warehouse} × {client_id} × {week}"
    return row.iloc[0][column]


@pytest.fixture
def trackflow_week() -> list[dict]:
    """Semana del 16-11-2026 calculada a mano.

    los_angeles × ecowear_usa: entradas de 20 y 5 uds. (Volumen = 25), 4 salidas
    (Throughput = 4), 1 cruce de umbral (Quiebres = 1) y 1 discrepancia
    (Tasa = 1 / 4 = 0,25).
    zaragoza × hydrolife: 1 entrada de 12 uds., 2 cruces de umbral y 1 discrepancia
    sin pedidos de salida (Tasa = 0, regla del BRIEFING).
    """
    return [
        telemetry_event(weekly_kpis.INBOUND, "2026-11-16T09:00:00Z", quantity=20),
        telemetry_event(weekly_kpis.INBOUND, "2026-11-18T09:00:00Z", quantity=5),
        telemetry_event(weekly_kpis.OUTBOUND, "2026-11-17T10:00:00Z"),
        telemetry_event(weekly_kpis.OUTBOUND, "2026-11-18T10:00:00Z"),
        telemetry_event(weekly_kpis.OUTBOUND, "2026-11-19T10:00:00Z"),
        telemetry_event(weekly_kpis.OUTBOUND, "2026-11-20T10:00:00Z"),
        telemetry_event(weekly_kpis.STOCKOUT, "2026-11-20T10:00:01Z", quantity=49),
        telemetry_event(weekly_kpis.DISCREPANCY, "2026-11-21T08:00:00Z", quantity=-2),
        telemetry_event(weekly_kpis.INBOUND, "2026-11-17T08:00:00Z", warehouse="zaragoza", client_id="hydrolife", quantity=12),
        telemetry_event(weekly_kpis.STOCKOUT, "2026-11-17T12:00:00Z", warehouse="zaragoza", client_id="hydrolife", quantity=40),
        telemetry_event(weekly_kpis.STOCKOUT, "2026-11-19T12:00:00Z", warehouse="zaragoza", client_id="hydrolife", quantity=30),
        telemetry_event(weekly_kpis.DISCREPANCY, "2026-11-20T12:00:00Z", warehouse="zaragoza", client_id="hydrolife", quantity=3),
    ]


# ---------------------------------------------------------------------------
# Un test por KPI de la sección "KPIs a medir"
# ---------------------------------------------------------------------------


def test_compute_inbound_volume_sums_units_not_orders(trackflow_week):
    volume = pipeline.compute_inbound_volume.fn(prepared(trackflow_week))

    assert kpi_value(volume, "inbound_units_count", "los_angeles", "ecowear_usa") == 25  # 20 + 5
    assert kpi_value(volume, "inbound_units_count", "zaragoza", "hydrolife") == 12


def test_compute_outbound_throughput_counts_dispatched_orders(trackflow_week):
    throughput = pipeline.compute_outbound_throughput.fn(prepared(trackflow_week))

    assert kpi_value(throughput, "outbound_orders_count", "los_angeles", "ecowear_usa") == 4
    assert ("zaragoza", "hydrolife") not in set(zip(throughput["warehouse"], throughput["client_id"], strict=True))


def test_compute_stockout_frequency_counts_threshold_crossings(trackflow_week):
    stockouts = pipeline.compute_stockout_frequency.fn(prepared(trackflow_week))

    assert kpi_value(stockouts, "stockout_events_count", "los_angeles", "ecowear_usa") == 1
    assert kpi_value(stockouts, "stockout_events_count", "zaragoza", "hydrolife") == 2


def test_compute_discrepancy_rate_matches_briefing_definition(trackflow_week):
    """Valor calculado a mano: 1 discrepancia / 4 pedidos de salida = 0,25."""
    events = prepared(trackflow_week)
    rows = pipeline.compute_discrepancy_rate.fn(
        events,
        pipeline.compute_inbound_volume.fn(events),
        pipeline.compute_outbound_throughput.fn(events),
        pipeline.compute_stockout_frequency.fn(events),
    )

    assert kpi_value(rows, "discrepancy_events_count", "los_angeles", "ecowear_usa") == 1
    assert kpi_value(rows, "discrepancy_rate", "los_angeles", "ecowear_usa") == pytest.approx(0.25)


def test_discrepancy_rate_is_zero_without_outbound_orders(trackflow_week):
    """BRIEFING §4: 0 si no hubo pedidos esa semana, aunque haya discrepancias."""
    events = prepared(trackflow_week)
    rows = pipeline.compute_discrepancy_rate.fn(
        events,
        pipeline.compute_inbound_volume.fn(events),
        pipeline.compute_outbound_throughput.fn(events),
        pipeline.compute_stockout_frequency.fn(events),
    )

    assert kpi_value(rows, "discrepancy_events_count", "zaragoza", "hydrolife") == 1
    assert kpi_value(rows, "outbound_orders_count", "zaragoza", "hydrolife") == 0
    assert kpi_value(rows, "discrepancy_rate", "zaragoza", "hydrolife") == 0.0


def test_weekly_rows_have_the_destination_table_columns(trackflow_week):
    events = prepared(trackflow_week)
    rows = pipeline.compute_discrepancy_rate.fn(
        events,
        pipeline.compute_inbound_volume.fn(events),
        pipeline.compute_outbound_throughput.fn(events),
        pipeline.compute_stockout_frequency.fn(events),
    )

    assert tuple(rows.columns) == (
        "warehouse",
        "client_id",
        "week_start",
        "inbound_units_count",
        "outbound_orders_count",
        "stockout_events_count",
        "discrepancy_events_count",
        "discrepancy_rate",
    )
    assert len(rows) == 2  # una fila por almacén × cliente: nunca se mezclan clientes
    assert pipeline.validate_weekly_kpis.fn(rows, [WEEK]) == 2


# ---------------------------------------------------------------------------
# Preparación: deduplicación, exclusión y semana ISO
# ---------------------------------------------------------------------------


def test_prepare_counts_a_retried_event_once():
    rows = [
        telemetry_event(weekly_kpis.OUTBOUND, "2026-11-17T10:00:00.000Z", event_id="same-event"),
        telemetry_event(weekly_kpis.OUTBOUND, "2026-11-17T10:00:00.300Z", event_id="same-event"),
    ]
    result = pipeline.prepare_kpi_events.fn(pd.DataFrame(rows), ())

    assert result.stats["duplicates_dropped"] == 1
    assert kpi_value(pipeline.compute_outbound_throughput.fn(result.events), "outbound_orders_count", "los_angeles", "ecowear_usa") == 1


def test_prepare_excludes_verification_events():
    rows = [
        telemetry_event(weekly_kpis.INBOUND, "2026-11-19T07:00:01Z", client_id="nova_beauty", quantity=12, user_id="curl_verification"),
        telemetry_event(weekly_kpis.INBOUND, "2026-11-19T05:56:53Z", quantity=1),
    ]
    result = pipeline.prepare_kpi_events.fn(pd.DataFrame(rows), ("curl_verification",))
    volume = pipeline.compute_inbound_volume.fn(result.events)

    assert result.stats["events_excluded"] == 1
    assert volume["client_id"].tolist() == ["ecowear_usa"]
    assert kpi_value(volume, "inbound_units_count", "los_angeles", "ecowear_usa") == 1


def test_prepare_assigns_iso_week_starting_monday_utc():
    rows = [
        telemetry_event(weekly_kpis.STOCKOUT, "2026-11-22T23:59:59Z", quantity=10),
        telemetry_event(weekly_kpis.STOCKOUT, "2026-11-23T00:00:00Z", quantity=10),
    ]
    stockouts = pipeline.compute_stockout_frequency.fn(prepared(rows))

    assert kpi_value(stockouts, "stockout_events_count", "los_angeles", "ecowear_usa", WEEK) == 1
    assert kpi_value(stockouts, "stockout_events_count", "los_angeles", "ecowear_usa", NEXT_WEEK) == 1


# ---------------------------------------------------------------------------
# Comportamiento defensivo ante entradas inválidas o malformadas
# ---------------------------------------------------------------------------


def test_prepare_rejects_malformed_rows_without_breaking_the_kpis():
    rows = [
        telemetry_event(weekly_kpis.INBOUND, "2026-11-17T09:00:00Z", quantity=20),  # válida
        telemetry_event(weekly_kpis.OUTBOUND, "2026-11-17T10:00:00Z", client_id=None),  # cliente nulo
        telemetry_event(weekly_kpis.INBOUND, "2026-11-17T11:00:00Z", quantity="veinte"),  # tipo incorrecto
        telemetry_event(weekly_kpis.INBOUND, "2026-11-17T12:00:00Z", quantity=0),  # cantidad no positiva
        telemetry_event(weekly_kpis.OUTBOUND, "no-es-una-fecha"),  # timestamp ilegible
        telemetry_event(weekly_kpis.OUTBOUND, "2026-11-17T13:00:00Z", warehouse="madrid"),  # almacén desconocido
        telemetry_event("page_viewed", "2026-11-17T14:00:00Z"),  # evento fuera del BRIEFING
    ]
    result = pipeline.prepare_kpi_events.fn(pd.DataFrame(rows), ())

    assert result.stats["rejected_by_reason"] == {
        "invalid_client_id": 1,
        "invalid_quantity": 2,
        "invalid_timestamp": 1,
        "invalid_warehouse": 1,
        "invalid_event_type": 1,
    }
    assert len(result.events) == 1
    assert kpi_value(pipeline.compute_inbound_volume.fn(result.events), "inbound_units_count", "los_angeles", "ecowear_usa") == 20


def test_prepare_raises_on_missing_extraction_columns():
    malformed = pd.DataFrame([{"timestamp": "2026-11-17T09:00:00Z", "event_type": weekly_kpis.INBOUND}])

    with pytest.raises(weekly_kpis.RawEventsSchemaError, match="event_id"):
        pipeline.prepare_kpi_events.fn(malformed, ())


def test_prepare_raises_on_wrong_input_type():
    with pytest.raises(TypeError, match="DataFrame"):
        pipeline.prepare_kpi_events.fn([{"event_type": weekly_kpis.INBOUND}], ())


def test_kpi_tasks_return_empty_frames_for_a_week_without_activity():
    events = prepared([])

    assert pipeline.compute_inbound_volume.fn(events).empty
    assert pipeline.compute_outbound_throughput.fn(events).empty
    assert pipeline.compute_stockout_frequency.fn(events).empty
