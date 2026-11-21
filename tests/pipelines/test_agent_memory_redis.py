"""El mismo contrato de memoria contra un Redis real (se omite si Redis no está arrancado).

    docker compose up -d redis
    python -m pytest tests/pipelines/test_agent_memory_redis.py -v

Usa un prefijo propio por test y borra sus claves al terminar: no toca la memoria
real del agente ni las colas de Celery.
"""

import uuid

import pytest

from services.agent.memory import flow
from services.agent.memory.backend import RedisBackend
from services.agent.memory.decision import DecisionClassification
from services.agent.memory.models import Actor, MemoryDraft
from services.agent.memory.store import MemoryStore

redis = pytest.importorskip("redis")

AGENT = Actor(user_id=7, role="user")
MESSAGE = "En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado."
DRAFT = MemoryDraft(category="carrier_rule", carrier="SEUR", country="ES", zone="zona rural de Zaragoza",
                    fact="SEUR ya no cubre la zona rural de Zaragoza: usar el carrier local desde el mes pasado.")


@pytest.fixture
def redis_store():
    backend = RedisBackend()
    try:
        backend.ping()
    except Exception:
        pytest.skip("Redis no está arrancado (docker compose up -d redis)")
    prefix = f"trackflow:agent_memory_test:{uuid.uuid4().hex[:8]}:"
    yield MemoryStore(backend, prefix=prefix)
    for key in backend.keys(prefix):
        backend.delete(key)


def test_full_cycle_against_redis(redis_store):
    proposal = flow.submit_proposal(redis_store, DRAFT, conversation_id="c-1", actor=AGENT, message=MESSAGE, run_id="r-1")
    assert proposal.status == "proposed"
    assert not redis_store.save_pending(redis_store.get_pending("c-1"))  # SET NX: una sola pendiente

    result = flow.apply_decision(
        redis_store, redis_store.get_pending("c-1"),
        DecisionClassification(label="approve", confidence=0.95, decided_by="llm"),
        message="sí", actor=AGENT, run_id="r-2",
    )

    assert result.outcome == "approved"
    assert [n["fact"] for n in flow.recall_notes(redis_store, "¿Qué carrier uso en la zona rural de Zaragoza?")] == [DRAFT.fact]
    assert [entry["event"] for entry in redis_store.audit_log()] == ["proposed", "approved"]  # Redis Stream
    assert redis_store.approvals_today(AGENT) == 1
