"""Configuración común de pytest.

* La memoria del agente y el registro de guardrails usan Redis en producción. En
  los tests se sustituyen por almacenes en memoria nuevos en cada test, para que
  ninguna prueba toque el Redis del Codespace (Celery) ni dependa de que esté arrancado.
* Las llamadas de generación del harness (respuesta de dominio y small talk) nunca
  llegan a un LLM real en los tests, aunque el `.env` tenga credenciales: fallan
  como un LLM caído, salvo que el test las sustituya. Así la suite es determinista.
* Lo mismo para los agentes del flujo de RFPs (`data/pipelines/rfp_intake/`): sin
  un doble explícito, todos caen a sus reglas deterministas.
* Los límites de intentos de autenticación (`services/api/rate_limit.py`) viven en
  memoria del proceso: se vacían antes de cada test para que un test no herede los
  fallos de login de otro.
* El presupuesto de llamadas al LLM (`services/agent/harness/usage_limits.py`, proyecto
  NIST) también vive en memoria: cada test empieza con un limitador nuevo y holgado
  (para que ninguna prueba que llama muchas veces al agente reciba 429); los tests
  del límite instalan el suyo con límites pequeños y un reloj falso.
* La Parte 3 de RFPs usa en los tests un checkpointer en memoria nuevo en cada test:
  ninguna prueba escribe `data/checkpoints/rfp_approval.sqlite` (las que prueban la
  persistencia en SQLite usan un fichero temporal propio).
"""

import pytest

from services.agent.harness import events as guard_events
from services.agent.harness import generation as agent_generation
from services.agent.harness import usage_limits
from services.agent.memory import store as memory_store
from services.agent.memory.backend import InMemoryBackend
from data.pipelines.rfp_intake import llm as rfp_llm
from services.api import rate_limit


@pytest.fixture(autouse=True)
def in_memory_agent_memory():
    store = memory_store.MemoryStore(InMemoryBackend())
    memory_store.set_store(store)
    yield store
    memory_store.set_store(None)


@pytest.fixture(autouse=True)
def in_memory_guardrail_log():
    log = guard_events.GuardrailLog(InMemoryBackend())
    guard_events.set_log(log)
    yield log
    guard_events.set_log(None)


@pytest.fixture(autouse=True)
def fresh_auth_rate_limits():
    rate_limit.reset_limiters()
    yield
    rate_limit.reset_limiters()


@pytest.fixture(autouse=True)
def roomy_llm_budget():
    usage_limits.reset_limiter(usage_limits.LlmUsageLimiter(10_000, 10_000, 10_000))
    yield
    usage_limits.reset_limiter(None)


@pytest.fixture(autouse=True)
def no_live_llm_in_generation(monkeypatch):
    def offline(*args, **kwargs):
        raise RuntimeError("sin LLM en los tests")

    monkeypatch.setattr(agent_generation, "_complete", offline)


@pytest.fixture(autouse=True)
def no_live_llm_in_rfp_intake(monkeypatch):
    def offline(system, user):
        raise RuntimeError("sin LLM en los tests")

    monkeypatch.setattr(rfp_llm, "complete", offline)


@pytest.fixture(autouse=True)
def in_memory_rfp_checkpointer():
    try:
        from langgraph.checkpoint.memory import InMemorySaver
    except ModuleNotFoundError:
        yield None
        return
    from data.pipelines.rfp_intake.approval import checkpoint

    saver = InMemorySaver()
    checkpoint.set_checkpointer(saver)
    yield saver
    checkpoint.set_checkpointer(None)
