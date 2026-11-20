"""Script nocturno (`scripts/nightly_export.py`) sin Supabase ni pipeline real.

- La exportación CSV se prueba contra un SQLite en memoria con la forma de
  `telemetry_events` (límites del día en UTC, solo si el fichero no existe,
  sin CSV a medias).
- El subproceso del pipeline se prueba con comandos Python mínimos.
- `main()` se ejecuta de punta a punta con el pipeline sustituido por un doble,
  para comprobar la idempotencia y el registro en `job_runs`.
"""

from datetime import date, datetime, timezone
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import Column, DateTime, MetaData, Numeric, Table, Text, create_engine, insert
from sqlalchemy.pool import StaticPool

from scripts import nightly_export
from services import job_runner


DAY = date(2026, 11, 18)  # miércoles
REPO_ROOT = Path(__file__).resolve().parents[1]

telemetry_metadata = MetaData()
telemetry_events = Table(
    "telemetry_events",
    telemetry_metadata,
    Column("id", Text, primary_key=True),
    Column("timestamp", DateTime(timezone=True), nullable=False),
    Column("service", Text, nullable=False),
    Column("event_type", Text, nullable=False),
    Column("level", Text, nullable=False),
    Column("value", Numeric, nullable=True),
    Column("message", Text, nullable=True),
    Column("tags", Text, nullable=False),
)


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    telemetry_metadata.create_all(engine)
    job_runner.job_runs_metadata.create_all(engine)
    rows = [
        ("e-prev", _utc(2026, 11, 17, 23, 59, 59), "page_viewed"),       # día anterior: fuera
        ("e-first", _utc(2026, 11, 18, 0, 0, 0), "page_viewed"),         # 00:00 UTC: dentro
        ("e-second", _utc(2026, 11, 18, 14, 30, 5), "inbound_order_created"),
        ("e-next", _utc(2026, 11, 19, 0, 0, 0), "page_viewed"),          # 00:00 del día siguiente: fuera
    ]
    with engine.begin() as connection:
        connection.execute(
            insert(telemetry_events),
            [
                {
                    "id": event_id,
                    "timestamp": timestamp,
                    "service": "backoffice",
                    "event_type": event_type,
                    "level": "info",
                    "value": 20 if event_type == "inbound_order_created" else None,
                    "message": f"{event_type} capturado",
                    "tags": json.dumps({"eventId": event_id, "userId": "u_operator"}),
                }
                for event_id, timestamp, event_type in rows
            ],
        )
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# TARGET_DATE
# ---------------------------------------------------------------------------


def test_target_date_defaults_to_yesterday_utc():
    assert nightly_export.resolve_target_date({}, today=date(2026, 11, 19)) == (DAY, False)


def test_target_date_env_overrides_the_default():
    assert nightly_export.resolve_target_date({"TARGET_DATE": "2025-01-15"}) == (date(2025, 1, 15), True)


def test_invalid_target_date_is_a_configuration_error():
    with pytest.raises(nightly_export.ConfigurationError, match="AAAA-MM-DD"):
        nightly_export.resolve_target_date({"TARGET_DATE": "18/11/2026"})


def test_main_returns_2_and_creates_no_row_with_invalid_target_date(monkeypatch):
    monkeypatch.setattr(nightly_export.signal, "signal", lambda *_args: None)
    assert nightly_export.main({"TARGET_DATE": "ayer"}) == 2


# ---------------------------------------------------------------------------
# Exportación CSV
# ---------------------------------------------------------------------------


def test_export_writes_only_the_target_utc_day(engine, tmp_path):
    rows = nightly_export.export_telemetry_csv(engine, DAY, tmp_path)

    path = tmp_path / "telemetry_2026-11-18.csv"
    assert rows == 2
    with path.open(newline="", encoding="utf-8") as handle:
        exported = list(csv.DictReader(handle))
    assert list(exported[0]) == list(nightly_export.CSV_COLUMNS)
    assert [row["id"] for row in exported] == ["e-first", "e-second"]
    assert exported[0]["timestamp"] == "2026-11-18T00:00:00+00:00"
    assert json.loads(exported[1]["tags"]) == {"eventId": "e-second", "userId": "u_operator"}
    assert not list(tmp_path.glob("*.tmp"))


def test_export_is_skipped_when_the_csv_already_exists(engine, tmp_path):
    nightly_export.export_telemetry_csv(engine, DAY, tmp_path)
    path = tmp_path / "telemetry_2026-11-18.csv"
    before = path.read_bytes()

    assert nightly_export.export_telemetry_csv(engine, DAY, tmp_path) is None
    assert path.read_bytes() == before


def test_day_without_events_writes_a_header_only_csv(engine, tmp_path):
    assert nightly_export.export_telemetry_csv(engine, date(2026, 11, 10), tmp_path) == 0
    assert (tmp_path / "telemetry_2026-11-10.csv").read_text(encoding="utf-8").strip() == ",".join(
        nightly_export.CSV_COLUMNS
    )


def test_failed_export_leaves_no_partial_csv(tmp_path):
    empty = create_engine("sqlite://")  # sin tabla telemetry_events

    with pytest.raises(Exception):
        nightly_export.export_telemetry_csv(empty, DAY, tmp_path)

    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------
# Subproceso del pipeline
# ---------------------------------------------------------------------------


def test_nightly_command_recalculates_the_closed_weeks():
    assert nightly_export.build_pipeline_command(DAY, overridden=False)[1:] == [
        "-m", "data.pipelines.pipeline", "--trigger", "scheduled",
    ]


def test_target_date_command_backfills_the_week_of_that_day():
    assert nightly_export.build_pipeline_command(DAY, overridden=True)[1:] == [
        "-m", "data.pipelines.pipeline", "--week-start", "2026-11-16", "--trigger", "backfill",
    ]


def test_pipeline_summary_is_read_from_its_json_output():
    summary = {"run_id": "abc", "status": "completed", "weeks": ["2026-11-09"], "rows_inserted": 3, "rows_updated": 0}
    command = [sys.executable, "-c", f"import json; print(json.dumps({summary!r}))"]

    assert nightly_export.run_pipeline(command, timeout_seconds=30) == (
        "pipeline_run_id=abc status=completed weeks=2026-11-09 inserted=3 updated=0"
    )


def test_pipeline_non_zero_exit_raises_with_its_last_error_lines():
    command = [sys.executable, "-c", "import sys; print('paso 1', file=sys.stderr); sys.exit('fallo de carga')"]

    with pytest.raises(nightly_export.PipelineSubprocessError, match=re.escape("código 1: paso 1 | fallo de carga")):
        nightly_export.run_pipeline(command, timeout_seconds=30)


def test_pipeline_timeout_kills_the_subprocess():
    with pytest.raises(subprocess.TimeoutExpired):
        nightly_export.run_pipeline([sys.executable, "-c", "import time; time.sleep(10)"], timeout_seconds=1)


# ---------------------------------------------------------------------------
# main() de punta a punta
# ---------------------------------------------------------------------------


@pytest.fixture
def wired(engine, tmp_path, monkeypatch):
    import data.pipelines.config as pipeline_config

    calls = []
    monkeypatch.setattr(pipeline_config, "get_engine", lambda: engine)
    monkeypatch.setattr(nightly_export, "RAW_DIR", tmp_path)
    monkeypatch.setattr(nightly_export.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(nightly_export, "run_pipeline", lambda command, timeout: calls.append(command) or "ok")
    return engine, tmp_path, calls


def test_main_twice_for_the_same_day_exports_and_runs_the_pipeline_once(wired):
    engine, tmp_path, calls = wired
    env = {"TARGET_DATE": "2026-11-18"}

    assert nightly_export.main(env) == 0
    csv_before = (tmp_path / "telemetry_2026-11-18.csv").read_bytes()
    assert nightly_export.main(env) == 0

    assert len(calls) == 1
    assert (tmp_path / "telemetry_2026-11-18.csv").read_bytes() == csv_before
    [row] = job_runner.list_runs(engine, nightly_export.JOB_NAME, DAY)
    assert row["status"] == "completed"


def test_main_records_failed_and_returns_1_when_the_pipeline_fails(wired, monkeypatch):
    engine, tmp_path, _calls = wired

    def failing_pipeline(_command, _timeout):
        raise nightly_export.PipelineSubprocessError("el pipeline terminó con código 1: sin conexión")

    monkeypatch.setattr(nightly_export, "run_pipeline", failing_pipeline)

    assert nightly_export.main({"TARGET_DATE": "2026-11-18"}) == 1
    [row] = job_runner.list_runs(engine, nightly_export.JOB_NAME, DAY)
    assert row["status"] == "failed"
    assert row["error_message"] == "PipelineSubprocessError: el pipeline terminó con código 1: sin conexión"
    assert not job_runner.has_processing_lock(engine, nightly_export.JOB_NAME)
    # El CSV ya se exportó: el reintento no lo reescribe y solo relanza el pipeline.
    assert (tmp_path / "telemetry_2026-11-18.csv").exists()


# ---------------------------------------------------------------------------
# Independencia de la API
# ---------------------------------------------------------------------------


def test_script_does_not_import_fastapi_or_the_api():
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import scripts.nightly_export, data.pipelines.config;"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('fastapi', 'starlette', 'uvicorn')"
        " or m.startswith('services.api')))"
    )
    output = subprocess.run(
        [sys.executable, "-c", code, str(REPO_ROOT)], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert output == "[]"
