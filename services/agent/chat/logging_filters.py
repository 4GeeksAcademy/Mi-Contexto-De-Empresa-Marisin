"""Redacta `token=…` en los logs de uvicorn: el WebSocket del chat lleva el JWT en la query.

uvicorn registra cada handshake en `uvicorn.error` como
`'%s - "WebSocket %s" [accepted]'` con la ruta **y su query** en los argumentos,
y las peticiones HTTP en `uvicorn.access`; sin este filtro el JWT acabaría en los
logs. Se instala al importar `services/agent/chat/router.py` (idempotente).
"""

from __future__ import annotations

import logging
import re
from typing import Any

TOKEN_PATTERN = re.compile(r"(?i)((?:^|[?&])token=)[^&\s\"']+")
REDACTED = "[redacted]"
LOGGER_NAMES = ("uvicorn.error", "uvicorn.access")


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


def install(logger_names: tuple[str, ...] = LOGGER_NAMES) -> None:
    for name in logger_names:
        target = logging.getLogger(name)
        if not any(isinstance(existing, RedactTokenFilter) for existing in target.filters):
            target.addFilter(RedactTokenFilter())
