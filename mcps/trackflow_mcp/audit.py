"""Log de auditoría: una línea JSON por invocación de tool (o intento rechazado).

Cada línea registra **qué tool**, **qué cliente** (`client_id` y `sub` del token),
con **qué scopes**, el **resultado** (`ok` o el código de error), la duración y
los nombres de los argumentos (sin valores, para no volcar datos al log). Se
escribe en `MCP_AUDIT_LOG` (por defecto `logs/mcp-tool-calls.jsonl`, ignorado
por git) y también en el logger `mcp.audit` (consola del servidor).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("mcp.audit")
_lock = threading.Lock()


class AuditLog:
    def __init__(self, path: Path | None):
        self.path = Path(path) if path else None

    def record(
        self,
        *,
        tool: str,
        client_id: str | None,
        subject: str | None,
        scopes: list[str],
        result: str,
        duration_ms: float,
        arguments: dict[str, Any] | None = None,
        status: int | None = None,
    ) -> dict[str, Any]:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "tool": tool,
            "client_id": client_id,
            "subject": subject,
            "scopes": sorted(scopes),
            "result": result,
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "argument_names": sorted((arguments or {}).keys()),
        }
        logger.info(
            "tool=%s client=%s result=%s status=%s %.1fms", tool, client_id, result, status, entry["duration_ms"]
        )
        if self.path is not None:
            line = json.dumps(entry, ensure_ascii=False)
            with _lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        return entry
