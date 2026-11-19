"""Máquina de estados de `job_runs` (`services/job_runner.py`) sin Supabase.

Se usa un SQLite en memoria con la misma tabla e índices (incluido el índice
único parcial que hace de lock): las transiciones, el lock vía `processing`,
la idempotencia por `target_date` y la ausencia de filas zombi se comprueban
contra una base de datos real, no contra dobles.
"""

from datetime import date, timedelta
import io
import logging

import pytest
from sqlalchemy import create_engine, func, insert, select
from sqlalchemy.pool import StaticPool

from services import job_runner
from services.job_runner import COMPLETED, FAILED, PENDING, PROCESSING, JobOutcome


JOB = "nightly_export"
DAY = date(2026, 11, 18)
STALE = timedelta(minutes=120)
LOGGER = logging.getLogger("tests.job_runner")


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    job_runner.job_runs_metadata.create_all(engine)
    yield engine
    engine.dispose()


def _insert(engine, *, status, target_date=DAY, started_ago=timedelta(minutes=1), job_name=JOB):
    from uuid import uuid4

    now = job_runner.utc_now()
    run_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            insert(job_runner.job_runs).values(
                id=run_id,
                job_name=job_name,
                target_date=target_date,
                status=status,
                started_at=None if status == PENDING else now - started_ago,
                finished_at=now if status in (COMPLETED, FAILED) else None,
                created_at=now - started_ago,
            )
        )
    return run_id


def _count(engine):
    with engine.connect() as connection:
        return connection.execute(select(func.count()).select_from(job_runner.job_runs)).scalar_one()


def _run(engine, work, target_date=DAY):
    return job_runner.run_job(
        engine, job_name=JOB, target_date=target_date, work=work, logger=LOGGER, stale_after=STALE
    )


# ---------------------------------------------------------------------------
# pending → processing → completed | failed
# ---------------------------------------------------------------------------


def test_successful_run_goes_pending_processing_completed(engine):
    seen = {}

    def work(run_id):
        seen["status_during_work"] = job_runner.get_run(engine, run_id)["status"]
        seen["lock_during_work"] = job_runner.has_processing_lock(engine, JOB)

    result = _run(engine, work)

    assert result.outcome is JobOutcome.COMPLETED
    assert seen == {"status_during_work": PROCESSING, "lock_during_work": True}
    row = job_runner.get_run(engine, result.run_id)
    assert row["status"] == COMPLETED
    assert row["target_date"] == DAY
    assert row["created_at"] is not None and row["started_at"] is not None and row["finished_at"] is not None
    assert row["error_message"] is None
    assert not job_runner.has_processing_lock(engine, JOB)


def test_exception_marks_failed_with_message_and_propagates(engine):
    def work(_run_id):
        raise ValueError("boom en la exportación")

    with pytest.raises(ValueError, match="boom"):
        _run(engine, work)

    [row] = job_runner.list_runs(engine, JOB, DAY)
    assert row["status"] == FAILED
    assert row["error_message"] == "ValueError: boom en la exportación"
    assert row["finished_at"] is not None
    assert not job_runner.has_processing_lock(engine, JOB)


@pytest.mark.parametrize("interruption", [SystemExit(143), KeyboardInterrupt()])
def test_sigterm_or_ctrl_c_never_leave_a_processing_row(engine, interruption):
    def work(_run_id):
        raise interruption

    with pytest.raises(type(interruption)):
        _run(engine, work)

    [row] = job_runner.list_runs(engine, JOB, DAY)
    assert row["status"] == FAILED
    assert row["error_message"].startswith(type(interruption).__name__)


def test_failed_day_is_retried_by_the_next_run(engine):
    _insert(engine, status=FAILED)
    calls = []

    result = _run(engine, calls.append)

    assert result.outcome is JobOutcome.COMPLETED
    assert len(calls) == 1
    assert [row["status"] for row in job_runner.list_runs(engine, JOB, DAY)] == [FAILED, COMPLETED]


# ---------------------------------------------------------------------------
# Lock vía processing
# ---------------------------------------------------------------------------


def test_second_instance_aborts_silently_when_processing_exists(engine):
    _insert(engine, status=PROCESSING, target_date=DAY - timedelta(days=1))
    calls = []

    result = _run(engine, calls.append)

    assert result == job_runner.JobResult(JobOutcome.SKIPPED_LOCKED, None)
    assert calls == []
    assert _count(engine) == 1


def test_processing_state_is_an_atomic_lock(engine):
    first = job_runner.create_run(engine, JOB, DAY)
    second = job_runner.create_run(engine, JOB, DAY)

    assert job_runner.mark_processing(engine, first) is True
    assert job_runner.mark_processing(engine, second) is False  # índice único parcial
    assert job_runner.get_run(engine, second)["status"] == PENDING

    job_runner.mark_completed(engine, first)
    assert job_runner.mark_processing(engine, second) is True  # el lock se liberó


def test_lock_is_per_job(engine):
    _insert(engine, status=PROCESSING, job_name="other_job")

    assert not job_runner.has_processing_lock(engine, JOB)
    assert _run(engine, lambda _run_id: None).outcome is JobOutcome.COMPLETED


def test_instance_that_loses_the_race_closes_its_row_and_does_no_work(engine, monkeypatch):
    # Simula dos arranques simultáneos: la comprobación previa no vio el lock,
    # pero cuando esta instancia intenta pasar a processing la otra ya lo tiene.
    _insert(engine, status=PROCESSING, target_date=DAY - timedelta(days=1))
    monkeypatch.setattr(job_runner, "has_processing_lock", lambda *_args: False)
    calls = []

    result = _run(engine, calls.append)

    assert result.outcome is JobOutcome.SKIPPED_LOCKED
    assert calls == []
    row = job_runner.get_run(engine, result.run_id)
    assert row["status"] == FAILED
    assert row["error_message"].startswith("Aborted:")


# ---------------------------------------------------------------------------
# Idempotencia por target_date
# ---------------------------------------------------------------------------


def test_completed_day_is_not_repeated(engine):
    calls = []

    first = _run(engine, calls.append)
    second = _run(engine, calls.append)

    assert first.outcome is JobOutcome.COMPLETED
    assert second == job_runner.JobResult(JobOutcome.SKIPPED_DUPLICATE, None)
    assert len(calls) == 1
    assert _count(engine) == 1


def test_idempotency_key_includes_target_date(engine):
    _insert(engine, status=COMPLETED, target_date=DAY - timedelta(days=1))
    calls = []

    result = _run(engine, calls.append)

    assert result.outcome is JobOutcome.COMPLETED
    assert len(calls) == 1
    assert job_runner.has_completed_for_date(engine, JOB, DAY)
    assert not job_runner.has_completed_for_date(engine, JOB, DAY + timedelta(days=1))


# ---------------------------------------------------------------------------
# Filas huérfanas
# ---------------------------------------------------------------------------


def test_stale_processing_row_is_closed_as_failed_and_releases_the_lock(engine):
    orphan = _insert(engine, status=PROCESSING, started_ago=timedelta(hours=3))
    recent = _insert(engine, status=PROCESSING, started_ago=timedelta(minutes=5), job_name="other_job")

    assert job_runner.recover_stale_runs(engine, JOB, STALE) == 1

    orphan_row = job_runner.get_run(engine, orphan)
    assert orphan_row["status"] == FAILED
    assert orphan_row["error_message"].startswith("StaleRun:")
    assert job_runner.get_run(engine, recent)["status"] == PROCESSING


def test_run_job_recovers_orphans_before_checking_the_lock(engine):
    _insert(engine, status=PROCESSING, started_ago=timedelta(hours=3))

    assert _run(engine, lambda _run_id: None).outcome is JobOutcome.COMPLETED


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def test_log_lines_include_timestamp_job_and_status():
    logger = job_runner.configure_job_logging("tests.job_runner.format")
    stream = io.StringIO()
    logger.handlers[0].setStream(stream)

    job_runner.log_event(logger, logging.INFO, COMPLETED, "Fin del trabajo.", job_name=JOB, target_date=DAY)

    line = stream.getvalue().strip()
    timestamp, level, job, status, target, run_id, message = line.split(" | ")
    assert timestamp.endswith("Z") and len(timestamp) == len("2026-11-19T01:15:02Z")
    assert (level, job, status, target, run_id, message) == (
        "INFO", "job=nightly_export", "status=completed", "target_date=2026-11-18", "run_id=-", "Fin del trabajo.",
    )
