"""Backends de almacenamiento de la memoria del agente.

`MemoryStore` solo usa estas operaciones, así que el backend se puede cambiar
sin tocar la lógica:

* `get` / `set` (con TTL y "solo si no existe") / `delete` / `keys`
* `incr` (contadores con caducidad: límite diario de escrituras por usuario)
* `append_log` / `read_log` (registro de auditoría *append-only*)

`RedisBackend` es el de producción: Redis ya está en el stack (broker de Celery,
`REDIS_URL`), con AOF activado en `docker-compose.yml`. La auditoría usa un
**Redis Stream** (`XADD`), que no se puede editar entrada a entrada.
`InMemoryBackend` es el de los tests y el modo `--backend memory` de los scripts.

Todas las claves llevan el prefijo `trackflow:agent_memory:`. Ninguna operación
toca Qdrant ni la colección `trackflow_knowledge` del RAG.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Protocol

KEY_PREFIX = "trackflow:agent_memory:"
REDIS_URL_ENV = "AGENT_MEMORY_REDIS_URL"  # opcional; por defecto, REDIS_URL
DEFAULT_REDIS_URL = "redis://localhost:6379/0"


class MemoryUnavailable(RuntimeError):
    """El almacén de memoria no responde. El agente sigue funcionando sin memoria."""


class MemoryBackend(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str, *, ttl_seconds: int | None = None, only_if_absent: bool = False) -> bool: ...
    def delete(self, key: str) -> None: ...
    def keys(self, prefix: str) -> list[str]: ...
    def incr(self, key: str, *, ttl_seconds: int) -> int: ...
    def append_log(self, key: str, entry: str) -> str: ...
    def read_log(self, key: str, *, count: int) -> list[str]: ...


def check_prefix(prefix: str) -> str:
    """La memoria nunca vive en el espacio del RAG (`*_knowledge`)."""
    if "knowledge" in prefix.lower():
        raise ValueError("La memoria del agente no puede escribir en colecciones *_knowledge del RAG")
    return prefix


class InMemoryBackend:
    """Backend en memoria con el mismo contrato (TTL incluido) que Redis."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._data: dict[str, tuple[str, float | None]] = {}
        self._logs: dict[str, list[str]] = {}

    def _alive(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        if item[1] is not None and item[1] <= self._clock():
            del self._data[key]
            return False
        return True

    def get(self, key: str) -> str | None:
        return self._data[key][0] if self._alive(key) else None

    def set(self, key: str, value: str, *, ttl_seconds: int | None = None, only_if_absent: bool = False) -> bool:
        if only_if_absent and self._alive(key):
            return False
        self._data[key] = (value, self._clock() + ttl_seconds if ttl_seconds else None)
        return True

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def keys(self, prefix: str) -> list[str]:
        return sorted(key for key in list(self._data) if key.startswith(prefix) and self._alive(key))

    def incr(self, key: str, *, ttl_seconds: int) -> int:
        current = int(self.get(key) or 0) + 1
        expires = self._data[key][1] if self._alive(key) else self._clock() + ttl_seconds
        self._data[key] = (str(current), expires)
        return current

    def append_log(self, key: str, entry: str) -> str:
        log = self._logs.setdefault(key, [])
        log.append(entry)
        return f"{int(self._clock() * 1000)}-{len(log)}"

    def read_log(self, key: str, *, count: int) -> list[str]:
        return list(self._logs.get(key, [])[-count:])


class RedisBackend:
    """Redis (`redis` ya es dependencia del proyecto por Celery)."""

    def __init__(self, url: str | None = None, *, client=None):
        if client is None:
            import redis  # import diferido: los tests no necesitan Redis

            url = url or os.environ.get(REDIS_URL_ENV) or os.environ.get("REDIS_URL") or DEFAULT_REDIS_URL
            client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
        self._redis = client

    def _call(self, method: str, *args, **kwargs):
        try:
            return getattr(self._redis, method)(*args, **kwargs)
        except Exception as exc:  # redis.ConnectionError, TimeoutError, OSError…
            raise MemoryUnavailable(f"Redis no responde ({type(exc).__name__}: {str(exc)[:120]})") from exc

    def ping(self) -> bool:
        return bool(self._call("ping"))

    def get(self, key: str) -> str | None:
        return self._call("get", key)

    def set(self, key: str, value: str, *, ttl_seconds: int | None = None, only_if_absent: bool = False) -> bool:
        return bool(self._call("set", key, value, ex=ttl_seconds, nx=only_if_absent))

    def delete(self, key: str) -> None:
        self._call("delete", key)

    def keys(self, prefix: str) -> list[str]:
        try:  # scan_iter es perezoso: los errores de conexión saltan al iterar
            return sorted(self._redis.scan_iter(match=f"{prefix}*", count=200))
        except Exception as exc:
            raise MemoryUnavailable(f"Redis no responde ({type(exc).__name__}: {str(exc)[:120]})") from exc

    def incr(self, key: str, *, ttl_seconds: int) -> int:
        value = int(self._call("incr", key))
        if value == 1:
            self._call("expire", key, ttl_seconds)
        return value

    def append_log(self, key: str, entry: str) -> str:
        return str(self._call("xadd", key, {"event": entry}))

    def read_log(self, key: str, *, count: int) -> list[str]:
        rows = self._call("xrevrange", key, count=count) or []
        return [fields["event"] for _, fields in reversed(rows)]
