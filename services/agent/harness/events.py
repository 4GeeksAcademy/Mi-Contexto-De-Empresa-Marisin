"""Observabilidad del harness: cada bloqueo, redirección o saneamiento queda registrado.

Cada evento lleva el **tipo de fallo** del enunciado:

* `structural` — salida con formato inesperado (JSON del enrutador inválido,
  respuesta vacía, sin línea «Fuente:», marcadores de plantilla…).
* `content` — alcance o datos: uso personal, small talk reconducido, pedido de
  otra sesión, datos sensibles del BRIEFING, mezcla de políticas por país.
* `security` — inyección directa (cambio de instrucciones, jailbreak) o
  indirecta (instrucciones dentro de un chunk RAG o de una tool), fuga del prompt.

Dónde queda:

1. **Log** `agent.guardrails` (una línea JSON por evento, nivel WARNING).
2. **Registro** `GuardrailLog`: Redis Stream bajo `trackflow:agent_guardrails:`
   (mismo Redis que la memoria) o en memoria en los tests. De ahí salen el
   resumen de `GET /agent/guardrails/summary` y `scripts/agent_guardrails_report.py`.
3. **Trace** de la corrida: los eventos de cada `run_id` se añaden al trace.

`record()` nunca lanza: si Redis no responde, el evento queda al menos en el log.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import uuid
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from ..memory.backend import InMemoryBackend, MemoryBackend, RedisBackend

logger = logging.getLogger("agent.guardrails")

KEY_PREFIX = "trackflow:agent_guardrails:"
BACKEND_ENV = "AGENT_GUARDRAILS_BACKEND"  # "redis" (por defecto) o "memory"
LOG_READ_LIMIT = 10_000


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Contexto de la corrida (lo fija el runner)
# --------------------------------------------------------------------------- #
_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("guardrail_context", default=None)


@contextmanager
def bind(*, run_id: str | None, conversation_id: str | None = None, user_id: int | None = None) -> Iterator[list[dict]]:
    """Asocia los eventos que se registren dentro del bloque a una corrida. Devuelve su lista."""
    collected: list[dict] = []
    token = _context.set({"run_id": run_id, "conversation_id": conversation_id, "user_id": user_id, "events": collected})
    try:
        yield collected
    finally:
        _context.reset(token)


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #
class GuardrailLog:
    def __init__(self, backend: MemoryBackend, *, prefix: str = KEY_PREFIX):
        self.backend = backend
        self.prefix = prefix

    def _key(self, *parts: str) -> str:
        return self.prefix + ":".join(parts)

    def append(self, event: dict[str, Any]) -> None:
        self.backend.append_log(self._key("events"), json.dumps(event, ensure_ascii=False, default=str))

    def read(self, limit: int = LOG_READ_LIMIT) -> list[dict[str, Any]]:
        return [json.loads(row) for row in self.backend.read_log(self._key("events"), count=limit)]

    def strikes(self, conversation_id: str) -> int:
        """Intentos de inyección en la conversación durante la última hora (incluido el actual)."""
        return self.backend.incr(self._key("strikes", conversation_id), ttl_seconds=3600)

    def summary(self, *, since: str | None = None) -> dict[str, Any]:
        rows = [row for row in self.read() if not since or row.get("at", "") >= since]
        count = lambda field: dict(Counter(row.get(field) or "-" for row in rows).most_common())  # noqa: E731
        by_guard_category = Counter(f"{row.get('guard')}:{row.get('category')}" for row in rows)
        return {
            "since": since,
            "total": len(rows),
            "by_guard": count("guard"),
            "by_category": count("category"),
            "by_failure_type": count("failure_type"),
            "by_action": count("action"),
            "by_guard_and_category": dict(by_guard_category.most_common()),
            "recent": rows[-20:],
        }


_log: GuardrailLog | None = None


def build_log(backend: str | None = None) -> GuardrailLog:
    kind = (backend or os.environ.get(BACKEND_ENV) or "redis").lower()
    return GuardrailLog(InMemoryBackend() if kind == "memory" else RedisBackend())


def get_log() -> GuardrailLog:
    global _log
    if _log is None:
        _log = build_log()
    return _log


def set_log(log: GuardrailLog | None) -> None:
    global _log
    _log = log


def record(
    *,
    guard: str,
    category: str,
    failure_type: str,
    action: str,
    rules: list[str] | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    """Registra un evento de guardrail (log + registro + trace de la corrida). No lanza nunca."""
    context = _context.get() or {}
    event = {
        "event_id": str(uuid.uuid4()),
        "at": utc_now().isoformat(timespec="seconds"),
        "guard": guard,
        "category": category,
        "failure_type": failure_type,
        "action": action,
        "rules": rules or [],
        "detail": (detail or "")[:200] or None,
        "run_id": context.get("run_id"),
        "conversation_id": context.get("conversation_id"),
        "user_id": context.get("user_id"),
    }
    event = {key: value for key, value in event.items() if value is not None}
    logger.warning("guardrail %s", json.dumps(event, ensure_ascii=False))
    try:
        get_log().append(event)
    except Exception as exc:  # Redis caído: el evento queda en el log
        logger.error("No se pudo guardar el evento de guardrail en el registro: %s", exc)
    if "events" in context:
        context["events"].append(event)
    return event
