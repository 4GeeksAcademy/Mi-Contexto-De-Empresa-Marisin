"""Configuración común de pytest.

La memoria del agente usa Redis en producción. En los tests se sustituye por un
almacén en memoria nuevo en cada test, para que ninguna prueba toque el Redis
del Codespace (Celery) ni dependa de que esté arrancado.
"""

import pytest

from services.agent.memory import store as memory_store
from services.agent.memory.backend import InMemoryBackend


@pytest.fixture(autouse=True)
def in_memory_agent_memory():
    store = memory_store.MemoryStore(InMemoryBackend())
    memory_store.set_store(store)
    yield store
    memory_store.set_store(None)
