"""Trace estructurado de cada corrida del agente (sin LangSmith).

Cada nodo del grafo se envuelve con `traced()`: registra en el `TraceRecorder`
de la corrida qué nodo se ejecutó, en qué orden, con qué entrada (resumida),
qué devolvió, cuánto tardó y, si falló, el error. El recorder viaja en una
`ContextVar`; LangGraph copia el contexto al lanzar cada nodo, así que todos
escriben en el mismo recorder aunque se ejecuten en otro hilo.

`runner.run_agent()` guarda el trace como JSON en `data/agent_traces/<run_id>.json`
(o en `AGENT_TRACE_DIR`), de modo que queda consultable después de la corrida:
en disco, con `load_trace()` o con `GET /agent/traces/{run_id}`.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[2]
TRACE_DIR_ENV = "AGENT_TRACE_DIR"
DEFAULT_TRACE_DIR = ROOT / "data" / "agent_traces"

_current_recorder: ContextVar["TraceRecorder | None"] = ContextVar("agent_trace_recorder", default=None)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def jsonable(value: Any) -> Any:
    """Copia serializable a JSON (lo que no lo es se convierte en texto)."""
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def summarize_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Resumen del estado para el trace: sin repetir los chunks completos."""
    state = state or {}
    return {
        "question": state.get("question"),
        "status": state.get("status"),
        "planned_sources": (state.get("route") or {}).get("sources"),
        "tool_status": {
            key.removesuffix("_result"): state[key]["status"]
            for key in ("ticket_result", "inventory_result")
            if isinstance(state.get(key), dict)
        },
        "context_chunks": len(state.get("context") or []),
        "has_answer": bool(state.get("answer")),
    }


@dataclass
class TraceRecorder:
    run_id: str
    question: str
    started_at: str = field(default_factory=utc_now)
    events: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        node: str,
        *,
        started_at: str,
        duration_ms: float,
        node_input: dict[str, Any],
        output: dict[str, Any] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events.append(
            {
                "step": len(self.events) + 1,
                "node": node,
                "started_at": started_at,
                "duration_ms": round(duration_ms, 2),
                "status": "error" if error else "ok",
                "input": node_input,
                "output": jsonable(output) if output is not None else None,
                "error": {"type": type(error).__name__, "message": str(error)[:500]} if error else None,
            }
        )

    @property
    def path(self) -> list[str]:
        return [event["node"] for event in self.events]

    @property
    def failed_node(self) -> str | None:
        return next((event["node"] for event in self.events if event["status"] == "error"), None)


@contextmanager
def recording(recorder: TraceRecorder) -> Iterator[TraceRecorder]:
    token = _current_recorder.set(recorder)
    try:
        yield recorder
    finally:
        _current_recorder.reset(token)


def traced(name: str, action: Callable[[Any], dict[str, Any]]) -> Callable[[Any], dict[str, Any]]:
    """Envuelve un nodo para registrar su ejecución en el recorder activo."""

    @wraps(action)
    def node(state):
        recorder = _current_recorder.get()
        started_at, start = utc_now(), time.perf_counter()
        try:
            output = action(state)
        except Exception as exc:
            if recorder is not None:
                recorder.record(
                    name,
                    started_at=started_at,
                    duration_ms=(time.perf_counter() - start) * 1000,
                    node_input=summarize_state(state),
                    error=exc,
                )
            raise
        if recorder is not None:
            recorder.record(
                name,
                started_at=started_at,
                duration_ms=(time.perf_counter() - start) * 1000,
                node_input=summarize_state(state),
                output=output,
            )
        return output

    return node


# --------------------------------------------------------------------------- #
# Persistencia
# --------------------------------------------------------------------------- #
def trace_dir(directory: str | Path | None = None) -> Path:
    if directory is not None:
        return Path(directory)
    return Path(os.environ.get(TRACE_DIR_ENV) or DEFAULT_TRACE_DIR)


def _valid_run_id(run_id: str) -> bool:
    try:
        return str(uuid.UUID(run_id)) == run_id
    except (ValueError, TypeError, AttributeError):
        return False


def save_trace(trace: dict[str, Any], directory: str | Path | None = None) -> Path:
    """Escribe el trace de forma atómica (`.tmp` + `os.replace`)."""
    if not _valid_run_id(trace.get("run_id", "")):
        raise ValueError("El trace necesita un run_id UUID válido")
    folder = trace_dir(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{trace['run_id']}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_trace(run_id: str, directory: str | Path | None = None) -> dict[str, Any] | None:
    """Trace de una corrida, o `None` si no existe. Solo acepta UUID (sin rutas)."""
    if not _valid_run_id(run_id):
        return None
    path = trace_dir(directory) / f"{run_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
