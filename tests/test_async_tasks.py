"""Cola de tareas asíncronas (Ticket #DEV-55) sin Redis ni Supabase.

- Las tareas se ejecutan con `Task.apply()` (modo eager de Celery): mismo código,
  reintentos incluidos, sin broker. El backoff no espera en este modo, pero el
  countdown se comprueba aparte.
- La DLQ se prueba contra un SQLite en memoria con la tabla real.
- `GET /tasks/{task_id}` se prueba sustituyendo `AsyncResult` por un doble.
"""

from datetime import datetime, timezone
import logging
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

from data.pipelines.triggers import ManualRunOutcome
from services import celery_app as task_queue
from services import dead_letter, tasks
from services.api.main import app
from services.api.routes import tasks as tasks_route
from services.api.security import get_current_user


# ---------------------------------------------------------------------------
# Configuración de Celery
# ---------------------------------------------------------------------------


def test_broker_and_backend_come_from_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    assert task_queue.redis_url() == "redis://redis:6379/0"
    monkeypatch.delenv("REDIS_URL")
    assert task_queue.redis_url() == "redis://localhost:6379/0"


def test_celery_config_follows_the_producer_consumer_rules():
    conf = task_queue.app.conf
    assert conf.task_acks_late is True  # ACK solo tras terminar
    assert conf.task_reject_on_worker_lost is True  # si el worker muere, vuelve a la cola
    assert conf.task_track_started is True  # el estado STARTED existe
    assert conf.task_time_limit and conf.task_soft_time_limit  # toda tarea tiene timeout
    assert conf.broker_transport_options["visibility_timeout"] > conf.task_time_limit
    assert {queue.name for queue in conf.task_queues} == {"celery", "dead_letter"}


def test_tasks_have_retries_and_time_limits():
    run = task_queue.app.tasks[task_queue.RUN_PIPELINE_TASK]
    assert run.max_retries == 3
    assert run.acks_late is True
    assert run.soft_time_limit and run.time_limit
    dlq = task_queue.app.tasks[task_queue.RECORD_DEAD_LETTER_TASK]
    assert dlq.soft_time_limit and dlq.time_limit


def test_retry_countdown_is_exponential():
    assert [task_queue.retry_countdown(retries) for retries in range(3)] == [5, 10, 20]


def test_enqueue_sends_only_references(monkeypatch):
    sent = []

    class FakeResult:
        id = "abc"

    def fake_send_task(name, **options):
        sent.append((name, options))
        return FakeResult()

    monkeypatch.setattr(task_queue.app, "send_task", fake_send_task)
    task_id = uuid4()
    assert task_queue.enqueue_pipeline_run(task_id, "2026-11-16", "1") == "abc"
    name, options = sent[0]
    assert name == "trackflow.reporting.run_pipeline"
    assert options["kwargs"] == {"week_start": "2026-11-16", "triggered_by": "1"}
    assert options["task_id"] == str(task_id)
    assert options["retry"] is False


def test_enqueue_wraps_broker_errors(monkeypatch):
    def broken(*args, **kwargs):
        raise ConnectionRefusedError("redis down")

    monkeypatch.setattr(task_queue.app, "send_task", broken)
    with pytest.raises(task_queue.BrokerUnavailableError):
        task_queue.enqueue_pipeline_run(uuid4(), None, "1")


# ---------------------------------------------------------------------------
# Tarea run_pipeline: éxito, cancelación, reintentos y DLQ
# ---------------------------------------------------------------------------


@pytest.fixture
def dead_letters(monkeypatch):
    sent = []
    monkeypatch.setattr(tasks, "send_to_dead_letter", sent.append)
    monkeypatch.delenv(tasks.FORCE_FAILURE_ENV, raising=False)
    return sent


def _apply_run_pipeline(task_id: str, **kwargs):
    return tasks.run_pipeline.apply(kwargs=kwargs, task_id=task_id, throw=False)


def test_run_pipeline_success_returns_the_summary(monkeypatch, dead_letters):
    calls = []

    def fake_flow(run_id, week_start, triggered_by):
        calls.append((run_id, week_start, triggered_by))
        return ManualRunOutcome(status="completed", summary={"status": "completed", "rows_inserted": 1})

    monkeypatch.setattr(tasks.triggers, "run_manual_flow", fake_flow)
    task_id = str(uuid4())
    result = _apply_run_pipeline(task_id, week_start="2026-11-16", triggered_by="1")

    assert result.state == "SUCCESS"
    assert result.result["pipeline_status"] == "completed"
    assert result.result["run_id"] == task_id  # primer intento: run_id = task_id
    assert result.result["attempt"] == 1
    assert result.result["summary"]["rows_inserted"] == 1
    assert calls[0][0] == UUID(task_id)
    assert str(calls[0][1]) == "2026-11-16"
    assert dead_letters == []


def test_run_pipeline_cancelled_is_not_a_failure(monkeypatch, dead_letters):
    monkeypatch.setattr(
        tasks.triggers,
        "run_manual_flow",
        lambda *args: ManualRunOutcome(status="cancelled", message="Ya hay una corrida en marcha"),
    )
    result = _apply_run_pipeline(str(uuid4()))
    assert result.state == "SUCCESS"
    assert result.result["pipeline_status"] == "cancelled"
    assert dead_letters == []


def test_run_pipeline_retries_then_succeeds(monkeypatch, dead_letters):
    run_ids = []

    def flaky(run_id, week_start, triggered_by):
        run_ids.append(run_id)
        if len(run_ids) < 3:
            return ManualRunOutcome(status="failed", error=OperationalError("select", {}, Exception("timeout")))
        return ManualRunOutcome(status="completed", summary={"status": "completed"})

    monkeypatch.setattr(tasks.triggers, "run_manual_flow", flaky)
    task_id = str(uuid4())
    result = _apply_run_pipeline(task_id)

    assert result.state == "SUCCESS"
    assert result.result["attempt"] == 3
    assert len(run_ids) == 3
    assert len(set(run_ids)) == 3  # cada intento abre su propia fila en pipeline_runs
    assert run_ids[0] == UUID(task_id)
    assert dead_letters == []


def test_run_pipeline_goes_to_dlq_after_max_retries(monkeypatch, dead_letters):
    monkeypatch.setenv(tasks.FORCE_FAILURE_ENV, "1")
    task_id = str(uuid4())
    result = _apply_run_pipeline(task_id, week_start=None, triggered_by="1")

    assert result.state == "FAILURE"
    assert isinstance(result.result, tasks.SimulatedTaskFailure)
    assert len(dead_letters) == 1
    letter = dead_letters[0]
    assert letter["task_id"] == task_id
    assert letter["task_name"] == "trackflow.reporting.run_pipeline"
    assert letter["attempt"] == 4  # 1 intento + 3 reintentos
    assert letter["max_retries"] == 3
    assert letter["error_type"] == "SimulatedTaskFailure"
    assert "intento 4" in letter["error_message"]
    assert letter["task_kwargs"] == {"week_start": None, "triggered_by": "1"}


def test_task_logs_id_attempt_state_and_duration(monkeypatch, dead_letters, caplog):
    monkeypatch.setenv(tasks.FORCE_FAILURE_ENV, "1")
    task_id = str(uuid4())
    with caplog.at_level(logging.INFO, logger="trackflow.tasks"):
        _apply_run_pipeline(task_id)
    lines = [record.getMessage() for record in caplog.records if task_id in record.getMessage()]
    assert any("attempt=1 state=RETRY duration_ms=" in line for line in lines)
    assert any("attempt=4 state=FAILURE duration_ms=" in line for line in lines)
    assert any("state=FAILURE error=SimulatedTaskFailure" in line for line in lines)


# ---------------------------------------------------------------------------
# DLQ persistida
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    dead_letter.dead_letters_metadata.create_all(engine)
    yield engine
    engine.dispose()


def _payload(task_id: str) -> dict:
    return dead_letter.build_payload(
        task_id=task_id,
        task_name="trackflow.reporting.run_pipeline",
        attempt=4,
        max_retries=3,
        exc=RuntimeError("boom"),
        task_kwargs={"week_start": "2026-11-16", "triggered_by": "1"},
    )


def test_dead_letter_record_is_idempotent(engine):
    task_id = str(uuid4())
    letter = dead_letter.from_payload(_payload(task_id))
    assert dead_letter.record(engine, letter) is True
    assert dead_letter.record(engine, letter) is False
    with engine.connect() as connection:
        count = connection.execute(select(func.count()).select_from(dead_letter.task_dead_letters)).scalar_one()
    assert count == 1
    row = dead_letter.get(engine, task_id)
    assert row["attempt"] == 4
    assert row["error_type"] == "RuntimeError"
    assert row["error_message"] == "boom"
    assert row["failed_at"] is not None


def test_record_dead_letter_task_persists_the_failure(monkeypatch, engine):
    monkeypatch.setattr(tasks, "_engine", lambda: engine)
    task_id = str(uuid4())
    result = tasks.record_dead_letter.apply(kwargs={"payload": _payload(task_id)}, throw=False)
    assert result.state == "SUCCESS"
    assert result.result == {"task_id": task_id, "attempt": 4, "recorded": True}
    assert dead_letter.get(engine, task_id)["task_kwargs"] == {"week_start": "2026-11-16", "triggered_by": "1"}


def test_dead_letter_payload_is_light_and_truncated():
    payload = dead_letter.build_payload(
        task_id="t",
        task_name="n",
        attempt=4,
        max_retries=3,
        exc=RuntimeError("x" * 10_000),
        task_kwargs={},
    )
    assert len(payload["error_message"]) == dead_letter.ERROR_MESSAGE_MAX_LENGTH
    assert datetime.fromisoformat(payload["failed_at"]).tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}
# ---------------------------------------------------------------------------


class FakeAsyncResult:
    def __init__(self, state, result=None):
        self.state = state
        self.result = result


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "is_active": True, "role": "admin"}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize(
    ("celery_state", "payload", "expected_status"),
    [
        ("PENDING", None, "pending"),
        ("STARTED", {"pid": 1, "hostname": "w"}, "started"),
        ("RETRY", RuntimeError("timeout"), "pending"),
        ("SUCCESS", {"pipeline_status": "completed"}, "success"),
        ("FAILURE", RuntimeError("boom"), "failure"),
    ],
)
def test_task_status_maps_celery_states(client, monkeypatch, celery_state, payload, expected_status):
    monkeypatch.setattr(tasks_route, "_async_result", lambda task_id: FakeAsyncResult(celery_state, payload))
    task_id = str(uuid4())
    response = client.get(f"/tasks/{task_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["status"] == expected_status
    assert body["celery_state"] == celery_state
    if celery_state == "SUCCESS":
        assert body["result"] == {"pipeline_status": "completed"}
        assert body["error"] is None
    elif celery_state in {"FAILURE", "RETRY"}:
        assert body["result"] is None
        assert body["error"].startswith("RuntimeError: ")
    else:
        assert body["result"] is None and body["error"] is None


def test_task_status_503_when_backend_is_down(client, monkeypatch):
    def broken(task_id):
        raise ConnectionRefusedError("redis down")

    monkeypatch.setattr(tasks_route, "_async_result", broken)
    response = client.get(f"/tasks/{uuid4()}")
    assert response.status_code == 503


def test_task_status_rejects_invalid_ids(client):
    assert client.get("/tasks/not-a-uuid").status_code == 422


def test_task_status_requires_session():
    app.dependency_overrides.pop(get_current_user, None)
    assert TestClient(app).get(f"/tasks/{uuid4()}").status_code == 401
