"""Flow principal y subflows del Pipeline de Desempeño de Negocio, sin base de datos.

Las funciones que tocan Supabase (`runs`, `extract`, `load`) se sustituyen por
dobles en memoria. Se comprueba la resiliencia del flow: tasks opcionales que
fallan sin tumbar la corrida, fallo de carga registrado en `pipeline_runs`,
corrida concurrente cancelada y caché de la transformación.
"""

from datetime import date
from uuid import UUID

import pandas as pd
import pytest

prefect = pytest.importorskip("prefect")

from prefect.testing.utilities import prefect_test_harness  # noqa: E402

from data.pipelines import pipeline  # noqa: E402
from data.pipelines.config import PipelineConfig  # noqa: E402
from data.process import weekly_kpis  # noqa: E402


WEEK = date(2026, 11, 16)


@pytest.fixture(scope="module", autouse=True)
def prefect_server():
    with prefect_test_harness():
        yield


def _events(*suffixes: str) -> pd.DataFrame:
    rows = [
        {
            "id": f"row-in-{suffix}",
            "timestamp": "2026-11-19T07:12:44+00:00",
            "event_type": weekly_kpis.INBOUND,
            "event_id": f"in-{suffix}",
            "warehouse": "los_angeles",
            "client_id": "ecowear_usa",
            "quantity": "20",
            "user_id": "u_operator",
            "request_id": f"req-in-{suffix}",
        }
        for suffix in suffixes
    ]
    rows.append(
        {
            "id": "row-curl",
            "timestamp": "2026-11-19T07:00:01+00:00",
            "event_type": weekly_kpis.INBOUND,
            "event_id": "curl-1",
            "warehouse": "los_angeles",
            "client_id": "nova_beauty",
            "quantity": "12",
            "user_id": "curl_verification",
            "request_id": "req-curl",
        }
    )
    return pd.DataFrame(rows)


class FakeDatabase:
    """Doble de `reporting.pipeline_runs` y de la tabla de destino."""

    def __init__(self, events: pd.DataFrame):
        self.events = events
        self.opened: list[UUID] = []
        self.closed: list[dict] = []
        self.phases: list[str] = []
        self.loads: list[list[dict]] = []
        self.active_run_id: UUID | None = None
        self.fail_load = False
        self.fail_coverage = True
        self.transform_calls = 0

    def open_run(self, engine, **kwargs):
        if self.active_run_id is not None:
            return pipeline.runs.OpenRunResult(False, kwargs["run_id"], self.active_run_id)
        self.opened.append(kwargs["run_id"])
        return pipeline.runs.OpenRunResult(True, kwargs["run_id"])

    def heartbeat(self, engine, run_id, phase, **counters):
        self.phases.append(phase)

    def close_run(self, engine, run_id, **kwargs):
        self.closed.append({"run_id": run_id, **kwargs})

    def extract_events(self, engine, window_start, window_end):
        return self.events

    def extract_source_signals(self, engine, window_start, window_end):
        return {"total_events": 46, "technical_events": 36, "source_max_timestamp": None}

    def extract_domain_orders(self, engine, window_start, window_end):
        if self.fail_coverage:
            raise ConnectionError("Supabase no responde")
        return pd.DataFrame([{"kind": "inbound", "warehouse": "Los Angeles", "orders": 1}])

    def upsert(self, engine, run_id, records, weeks):
        if self.fail_load:
            raise ConnectionError("timeout de Supabase en la carga")
        self.loads.append(records)
        return {"rows_inserted": len(records), "rows_updated": 0, "rows_unchanged": 0, "rows_deleted": 0}


@pytest.fixture
def fake_db(monkeypatch, tmp_path):
    fake = FakeDatabase(_events("a"))
    monkeypatch.setattr(pipeline, "get_engine", lambda: object())
    monkeypatch.setattr(pipeline, "load_config", PipelineConfig)
    monkeypatch.setattr(pipeline, "EVAL_SNAPSHOT_PATH", tmp_path / "snapshot.json")
    monkeypatch.setattr(pipeline.runs, "open_run", fake.open_run)
    monkeypatch.setattr(pipeline.runs, "heartbeat", fake.heartbeat)
    monkeypatch.setattr(pipeline.runs, "close_run", fake.close_run)
    monkeypatch.setattr(pipeline.extract, "extract_events", fake.extract_events)
    monkeypatch.setattr(pipeline.extract, "extract_source_signals", fake.extract_source_signals)
    monkeypatch.setattr(pipeline.extract, "extract_domain_orders", fake.extract_domain_orders)
    monkeypatch.setattr(pipeline.load, "upsert_weekly_kpis", fake.upsert)
    # Sin esperas en los tests: los reintentos reales (30 s) se prueban por configuración.
    for name in ("load_weekly_kpis", "check_capture_coverage", "extract_kpi_events"):
        monkeypatch.setattr(pipeline, name, getattr(pipeline, name).with_options(retries=0))
    return fake


def test_external_tasks_declare_retries():
    assert pipeline.extract_kpi_events.retries == 3
    assert pipeline.load_weekly_kpis.retries == 3
    assert pipeline.open_pipeline_run.retries > 0
    assert pipeline.close_pipeline_run.retries > 0


def test_prepare_task_declares_cache():
    assert pipeline.prepare_kpi_events.cache_key_fn is not None
    assert pipeline.prepare_kpi_events.cache_expiration.total_seconds() == 3600


def test_prepare_cache_key_never_matches_the_part_2_transform_key():
    """Regresión: la clave de la Parte 2 (`weekly-kpis-v1-…`) guardaba un TransformResult.

    Si prepare_kpi_events la reutilizara, Prefect serviría ese objeto y el subflow
    de transformación fallaría con "'TransformResult' object has no attribute 'events'".
    """
    events = _events("cache-key")
    key = pipeline._prepare_cache_key(None, {"raw_events": events, "excluded_user_ids": ("curl_verification",)})
    part_2_key = f"weekly-kpis-v1-{weekly_kpis.events_fingerprint(events)}"

    assert key.startswith("prepare-kpi-events-weekly-kpis-v2-")
    assert not key.startswith(part_2_key)
    assert weekly_kpis.TRANSFORM_VERSION != "1"


def test_flow_completes_when_optional_task_fails(fake_db):
    summary = pipeline.weekly_warehouse_client_performance_flow(week_start=WEEK, trigger="manual")

    assert summary["status"] == "completed"
    assert "check_capture_coverage_failed:ConnectionError" in summary["warnings"]
    assert fake_db.loads == [
        [
            {
                "warehouse": "los_angeles",
                "client_id": "ecowear_usa",
                "week_start": WEEK,
                "inbound_units_count": 20,
                "outbound_orders_count": 0,
                "stockout_events_count": 0,
                "discrepancy_events_count": 0,
                "discrepancy_rate": 0.0,
            }
        ]
    ]
    assert fake_db.phases == ["extract", "validate"]
    assert fake_db.closed[-1]["status"] == "completed"
    assert pipeline.EVAL_SNAPSHOT_PATH.exists()


def test_load_failure_is_recorded_and_stops_the_flow(fake_db):
    fake_db.events = _events("b")
    fake_db.fail_load = True

    state = pipeline.weekly_warehouse_client_performance_flow(
        week_start=WEEK, trigger="manual", return_state=True
    )

    assert state.is_failed()
    assert fake_db.loads == []
    assert fake_db.closed[-1]["status"] == "failed"
    assert fake_db.closed[-1]["error_type"] == "ConnectionError"
    assert "load" in fake_db.closed[-1]["error_message"]


def test_concurrent_run_is_cancelled(fake_db):
    fake_db.active_run_id = UUID("11111111-1111-1111-1111-111111111111")

    state = pipeline.weekly_warehouse_client_performance_flow(
        week_start=WEEK, trigger="manual", return_state=True
    )

    assert state.is_cancelled()
    assert fake_db.opened == []
    assert fake_db.loads == []


def test_second_run_on_same_data_reuses_transform_cache(fake_db, monkeypatch):
    fake_db.events = _events("cache", "cache-2")
    fake_db.fail_coverage = False
    calls = []
    original = weekly_kpis.prepare_events

    def counting(raw_events, excluded_user_ids=()):
        calls.append(len(raw_events))
        return original(raw_events, excluded_user_ids)

    monkeypatch.setattr(pipeline.weekly_kpis, "prepare_events", counting)
    first = pipeline.weekly_warehouse_client_performance_flow(week_start=WEEK, trigger="manual")
    second = pipeline.weekly_warehouse_client_performance_flow(week_start=WEEK, trigger="manual")

    assert first["kpi_rows"] == second["kpi_rows"] == 1
    assert fake_db.loads[0] == fake_db.loads[1]  # misma carga: el upsert deja el mismo estado
    assert len(calls) <= 1  # la segunda corrida sale de la caché (0 si ya estaba cacheada)


def test_main_flow_coordinates_subflows():
    """El flow principal delega cada etapa en un subflow (Parte 3)."""
    subflows = [
        pipeline.extract_warehouse_client_kpi_events_flow,
        pipeline.compute_weekly_warehouse_client_kpis_flow,
        pipeline.load_weekly_warehouse_client_performance_flow,
        pipeline.check_capture_coverage_flow,
        pipeline.export_weekly_performance_snapshot_flow,
    ]
    assert all(isinstance(subflow, prefect.Flow) for subflow in subflows)
    assert {subflow.name for subflow in subflows} == {
        "extract_warehouse_client_kpi_events",
        "compute_weekly_warehouse_client_kpis",
        "load_weekly_warehouse_client_performance",
        "check_capture_coverage",
        "export_weekly_performance_snapshot",
    }


def test_compute_subflow_runs_on_its_own():
    """El subflow de transformación corre aislado, con eventos en memoria."""
    result = pipeline.compute_weekly_warehouse_client_kpis_flow(
        _events("standalone"), ("curl_verification",), [WEEK]
    )
    assert weekly_kpis.kpis_to_records(result.kpis) == [
        {
            "warehouse": "los_angeles",
            "client_id": "ecowear_usa",
            "week_start": WEEK,
            "inbound_units_count": 20,
            "outbound_orders_count": 0,
            "stockout_events_count": 0,
            "discrepancy_events_count": 0,
            "discrepancy_rate": 0.0,
        }
    ]
    assert result.stats["events_excluded"] == 1


def test_extract_and_load_subflows_run_on_their_own(fake_db):
    extracted = pipeline.extract_warehouse_client_kpi_events_flow(WEEK, date(2026, 11, 23))
    assert len(extracted["events"]) == 2
    kpis = weekly_kpis.transform_events(extracted["events"], ("curl_verification",)).kpis
    counts = pipeline.load_weekly_warehouse_client_performance_flow(
        UUID("22222222-2222-2222-2222-222222222222"), kpis, [WEEK]
    )
    assert counts["rows_inserted"] == 1
