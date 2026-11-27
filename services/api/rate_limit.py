"""Límite de intentos de autenticación (auditoría OWASP · H1, A07/A09; decisión D14).

Ventana deslizante **en memoria** y thread-safe (las rutas síncronas de FastAPI
corren en un pool de hilos). Política:

* `POST /auth/login`: 5 **fallos** por pareja `(ip, email)` y 20 fallos por IP en
  15 minutos → 429 con `Retry-After`. Un login correcto limpia el contador de la
  pareja (no el de la IP).
* `POST /auth/forgot-password`: 3 peticiones por `(ip, email)` en 15 minutos → 429.

La IP es `request.client.host`: **no** se confía en `X-Forwarded-For`, que el
cliente puede falsificar. Detrás de un proxy inverso habría que leer la cabecera
solo de la IP del proxy. El estado vive en el proceso: con un único uvicorn es
suficiente; con varias instancias el contador iría a Redis.

Los eventos de seguridad van al logger `api.security` con el email **resumido**
(`email_hash`, SHA-256 truncado a 12 caracteres): nunca el email en claro ni la contraseña.
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from collections import deque
from typing import Callable, Hashable

WINDOW_SECONDS = 15 * 60
LOGIN_FAILURES_PER_PAIR = 5
LOGIN_FAILURES_PER_IP = 20
FORGOT_PASSWORD_PER_PAIR = 3
TOO_MANY_ATTEMPTS_DETAIL = "Demasiados intentos. Inténtalo de nuevo más tarde."


class SlidingWindowLimiter:
    """Cuenta eventos por clave en los últimos `window_seconds`; bloquea al llegar a `limit`."""

    def __init__(self, limit: int, window_seconds: float = WINDOW_SECONDS,
                 clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._events: dict[Hashable, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: Hashable, now: float) -> deque[float]:
        events = self._events.get(key)
        if events is None:
            return deque()
        while events and events[0] <= now - self.window_seconds:
            events.popleft()
        if not events:
            del self._events[key]
        return events

    def retry_after(self, key: Hashable) -> int | None:
        """Segundos hasta que `key` pueda volver a intentarlo, o `None` si no está bloqueada."""
        with self._lock:
            now = self.clock()
            events = self._prune(key, now)
            if len(events) < self.limit:
                return None
            return max(1, math.ceil(events[0] + self.window_seconds - now))

    def hit(self, key: Hashable) -> None:
        """Registra un evento (un fallo de login, una petición de recuperación)."""
        with self._lock:
            now = self.clock()
            self._prune(key, now)
            self._events.setdefault(key, deque()).append(now)

    def acquire(self, key: Hashable) -> int | None:
        """Comprueba y registra en un solo paso (atómico): `None` si cabe, o los segundos de espera.

        Lo usa el límite de llamadas al LLM (proyecto NIST): cada petición aceptada
        consume una unidad; una rechazada no consume nada.
        """
        with self._lock:
            now = self.clock()
            events = self._prune(key, now)
            if len(events) >= self.limit:
                return max(1, math.ceil(events[0] + self.window_seconds - now))
            self._events.setdefault(key, deque()).append(now)
            return None

    def reset(self, key: Hashable) -> None:
        with self._lock:
            self._events.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


login_pair_limiter = SlidingWindowLimiter(LOGIN_FAILURES_PER_PAIR)
login_ip_limiter = SlidingWindowLimiter(LOGIN_FAILURES_PER_IP)
forgot_password_limiter = SlidingWindowLimiter(FORGOT_PASSWORD_PER_PAIR)


def reset_limiters() -> None:
    """Vacía todos los contadores (tests)."""
    for limiter in (login_pair_limiter, login_ip_limiter, forgot_password_limiter):
        limiter.clear()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def email_hash(email: str) -> str:
    """Identificador estable del email para los logs, sin el email en claro."""
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()[:12]


def client_ip(request) -> str:
    """IP del socket (`request.client.host`); no se confía en `X-Forwarded-For`."""
    return request.client.host if request.client else "unknown"
