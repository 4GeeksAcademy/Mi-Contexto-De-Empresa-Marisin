"""Redacta `token=…` en los logs de uvicorn: el WebSocket del chat lleva el JWT en la query.

uvicorn registra cada handshake en `uvicorn.error` como
`'%s - "WebSocket %s" [accepted]'` con la ruta **y su query** en los argumentos,
y las peticiones HTTP en `uvicorn.access`; sin este filtro el JWT acabaría en los
logs. Se instala al importar `services/agent/chat/router.py` (idempotente).

Además da un handler de consola (como `api.timing` en `services/api/main.py`) a
`api.agent.chat` y `agent.runner`: sin él, sus INFO (`cancelled … stream_closed=…
dropped_after_abort=…`) no salen en la consola de uvicorn.
"""

from __future__ import annotations

import logging
import re
from typing import Any

TOKEN_PATTERN = re.compile(r"(?i)((?:^|[?&])token=)[^&\s\"']+")
REDACTED = "[redacted]"
LOGGER_NAMES = ("uvicorn.error", "uvicorn.access")
CONSOLE_LOGGERS = ("api.agent.chat", "agent.runner", "agent.audit")


def redact(text: str) -> str:
    return TOKEN_PATTERN.sub(lambda match: match.group(1) + REDACTED, text)


def _redact_value(value: Any) -> Any:
    return redact(value) if isinstance(value, str) and "token=" in value.lower() else value


class RedactTokenFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact_value(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_value(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact_value(value) for key, value in record.args.items()}
        return True


def show_in_console(name: str) -> None:
    """Igual que `api.timing` en `services/api/main.py`: sin handler, el INFO no llega a la consola de uvicorn."""
    target = logging.getLogger(name)
    target.setLevel(logging.INFO)
    if not target.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        target.addHandler(handler)
    target.propagate = False


def install(logger_names: tuple[str, ...] = LOGGER_NAMES) -> None:
    for name in logger_names:
        target = logging.getLogger(name)
        if not any(isinstance(existing, RedactTokenFilter) for existing in target.filters):
            target.addFilter(RedactTokenFilter())
    # Las líneas `chat session=… cancelled … dropped_after_abort=…` y
    # `agent run_id=… cancelled tokens_sent=… stream_closed=…` que cita la verificación manual.
    for name in CONSOLE_LOGGERS:
        show_in_console(name)
