"""Configuración común de pytest.

* La memoria del agente y el registro de guardrails usan Redis en producción. En
  los tests se sustituyen por almacenes en memoria nuevos en cada test, para que
  ninguna prueba toque el Redis del Codespace (Celery) ni dependa de que esté arrancado.
* Las llamadas de generación del harness (respuesta de dominio y small talk) nunca
  llegan a un LLM real en los tests, aunque el `.env` tenga credenciales: fallan
  como un LLM caído, salvo que el test las sustituya. Así la suite es determinista.
"""

import pytest

from services.agent.harness import events as guard_events
from services.agent.harness import generation as agent_generation
from services.agent.memory import store as memory_store
from services.agent.memory.backend import InMemoryBackend


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
def no_live_llm_in_generation(monkeypatch):
    def offline(*args, **kwargs):
        raise RuntimeError("sin LLM en los tests")

    monkeypatch.setattr(agent_generation, "_complete", offline)
