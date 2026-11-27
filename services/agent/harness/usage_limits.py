"""Límite de llamadas a los endpoints que invocan un modelo (proyecto NIST · Protect, PR.PS / OWASP LLM10).

Cada consulta al agente de CX o al RAG dispara una o varias llamadas al LLM de
4Geeks (enrutador + generación) y a los embeddings. Sin límite, un cliente con un
bucle (o un script que reintenta sin parar) dispara el coste y deja sin servicio
al resto. La política, por **presupuesto compartido** entre todas las entradas que
llaman al modelo (`POST /agent/query`, chat por WebSocket y `POST /knowledge/query`):

| Ventana | Clave | Límite por defecto | Variable |
|---|---|---|---|
| 60 s | usuario | 10 | `LLM_RATE_LIMIT_PER_MINUTE` |
| 24 h | usuario | 200 | `LLM_RATE_LIMIT_PER_DAY` |
| 60 s | todos los usuarios (cortacircuitos de coste) | 60 | `LLM_GLOBAL_RATE_LIMIT_PER_MINUTE` |

* Solo **consume** una petición aceptada; una rechazada no gasta presupuesto.
* La clave es el `id` del usuario autenticado (todas las entradas exigen JWT),
  no la IP: detrás del proxy de Codespaces todas las IPs son la misma.
* Sin usuario (CLI, evals grabados, scripts) no hay límite: son ejecuciones internas.
* El rechazo deja un evento de guardrail (`guard = rate_limit`, tipo de fallo
  `security`), visible en `GET /agent/guardrails/summary` y en el log.

El estado vive en memoria del proceso (igual que el límite de login de OWASP H1):
con varias instancias el contador iría a Redis (`INCR` + `EXPIRE`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

try:
    from services.api.rate_limit import SlidingWindowLimiter
except ModuleNotFoundError as exc:  # contenedor: /app es `services/`
    if exc.name not in {"services", "services.api"}:
        raise
    from api.rate_limit import SlidingWindowLimiter  # type: ignore[no-redef]

from . import events

MINUTE = 60
DAY = 24 * 60 * 60
DEFAULT_PER_MINUTE = 10
DEFAULT_PER_DAY = 200
DEFAULT_GLOBAL_PER_MINUTE = 60
RATE_LIMITED_DETAIL = (
    "Has hecho demasiadas consultas al asistente en poco tiempo. Espera un momento y vuelve a intentarlo."
)


def _int_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class LimitVerdict:
    allowed: bool
    retry_after: int | None = None
    scope: str | None = None  # "user_minute" | "user_day" | "global_minute"


class LlmUsageLimiter:
    """Tres ventanas deslizantes; una petición pasa solo si cabe en las tres."""

    def __init__(self, per_minute: int, per_day: int, global_per_minute: int, clock=None):
        kwargs = {"clock": clock} if clock else {}
        self.per_minute = per_minute
        self.per_day = per_day
        self.global_per_minute = global_per_minute
        self.user_minute = SlidingWindowLimiter(per_minute, MINUTE, **kwargs)
        self.user_day = SlidingWindowLimiter(per_day, DAY, **kwargs)
        self.global_minute = SlidingWindowLimiter(global_per_minute, MINUTE, **kwargs)

    def check(self, user_key: str) -> LimitVerdict:
        # Primero se mira sin consumir; después se consume en las tres ventanas.
        for scope, limiter, key in self._windows(user_key):
            wait = limiter.retry_after(key)
            if wait is not None:
                return LimitVerdict(False, wait, scope)
        for scope, limiter, key in self._windows(user_key):
            wait = limiter.acquire(key)
            if wait is not None:  # carrera entre hilos: otro consumió la última unidad
                return LimitVerdict(False, wait, scope)
        return LimitVerdict(True)

    def _windows(self, user_key: str):
        return (
            ("global_minute", self.global_minute, "global"),
            ("user_minute", self.user_minute, user_key),
            ("user_day", self.user_day, user_key),
        )

    def clear(self) -> None:
        for _, limiter, _key in self._windows(""):
            limiter.clear()


def build_limiter(clock=None) -> LlmUsageLimiter:
    return LlmUsageLimiter(
        _int_env("LLM_RATE_LIMIT_PER_MINUTE", DEFAULT_PER_MINUTE),
        _int_env("LLM_RATE_LIMIT_PER_DAY", DEFAULT_PER_DAY),
        _int_env("LLM_GLOBAL_RATE_LIMIT_PER_MINUTE", DEFAULT_GLOBAL_PER_MINUTE),
        clock=clock,
    )


_limiter: LlmUsageLimiter | None = None


def get_limiter() -> LlmUsageLimiter:
    global _limiter
    if _limiter is None:
        _limiter = build_limiter()
    return _limiter


def reset_limiter(limiter: LlmUsageLimiter | None = None) -> None:
    """Tests: vacía los contadores o instala un limitador propio (otro reloj, otros límites)."""
    global _limiter
    _limiter = limiter


def user_key(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    ident = user.get("id") or user.get("uuid") or user.get("email")
    return f"user:{ident}" if ident is not None else None


def consume(user: dict[str, Any] | None, *, endpoint: str) -> LimitVerdict:
    """Gasta una unidad del presupuesto del usuario para `endpoint`, o devuelve el rechazo."""
    key = user_key(user)
    if key is None:
        return LimitVerdict(True)
    verdict = get_limiter().check(key)
    if not verdict.allowed:
        with events.bind(run_id=None, user_id=user.get("id")):
            events.record(
                guard="rate_limit", category="llm_budget", failure_type="security", action="block",
                rules=[verdict.scope or "unknown"],
                detail=f"{endpoint} role={user.get('role')} retry_after={verdict.retry_after}s",
            )
    return verdict
