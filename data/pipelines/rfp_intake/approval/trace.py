"""Trazabilidad: qué agente hizo qué, con qué entrada y salida, y cuándo.

Cada nodo de los grafos de la Parte 3 se envuelve con `traced(agent, node, …)`:

- añade una entrada a `trace` en el estado del grafo (reductor de suma, queda
  en el checkpoint de su hilo) con `agent`, `node`, `graph`, `thread_id`,
  `input`, `output`, `started_at`, `finished_at` y `duration_ms`;
- y la entrega al `TraceSink` del runner, que la guarda en PostgreSQL
  (`rfp_trace_events`) para ver la ejecución completa del ticket —ticket y
  ramas— en orden, aunque cada rama tenga su propio checkpoint.

Un nodo que se pausa con `interrupt()` deja una entrada `interrupted` (con lo que
espera); al reanudarse, LangGraph lo vuelve a ejecutar desde el principio y deja
su entrada normal con la decisión. Un nodo que falla deja una entrada `error`.
La entrada y la salida se resumen (`summarize`) para que la traza no copie
borradores enteros en cada paso.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol

MAX_TEXT = 300
MAX_ITEMS = 12


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize(value: Any, depth: int = 0) -> Any:
    """Copia JSON acotada: textos largos recortados, listas y anidación limitadas."""
    if isinstance(value, str):
        return value if len(value) <= MAX_TEXT else f"{value[:MAX_TEXT]}… ({len(value)} caracteres)"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if depth >= 3:
        return f"<{type(value).__name__}>"
    if isinstance(value, dict):
        return {str(k): summarize(v, depth + 1) for k, v in list(value.items())[:MAX_ITEMS * 2]}
    if isinstance(value, (list, tuple)):
        items = [summarize(v, depth + 1) for v in list(value)[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"… {len(value) - MAX_ITEMS} más")
        return items
    return str(value)[:MAX_TEXT]


class TraceSink(Protocol):
    def record(self, entry: dict[str, Any]) -> None: ...


class NullSink:
    def record(self, entry):
        pass


class ListSink:
    """Guarda las entradas en orden (tests, CLI)."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, entry):
        self.entries.append(entry)


def _is_interrupt(exc: BaseException) -> bool:
    # GraphInterrupt (langgraph.errors) y sus variantes: el nodo se pausa, no falla.
    return any(cls.__name__ in {"GraphInterrupt", "NodeInterrupt"} for cls in type(exc).__mro__)


def _interrupt_value(exc: BaseException) -> Any:
    interrupts = getattr(exc, "interrupts", None) or (exc.args[0] if exc.args else ())
    try:
        return [getattr(item, "value", item) for item in interrupts]
    except TypeError:
        return None


def traced(
    agent: str | Callable[[dict[str, Any]], str],
    node: str,
    fn: Callable[[dict[str, Any]], dict[str, Any]],
    *,
    graph: str,
    thread_id: Callable[[dict[str, Any]], str],
    sink: TraceSink | None,
    input_keys: tuple[str, ...] = (),
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Envuelve un nodo: ejecuta, mide y registra la entrada de traza (en el estado y en el sink)."""
    sink = sink or NullSink()

    def run(state: dict[str, Any]) -> dict[str, Any]:
        started = utc_iso()
        clock = time.perf_counter()
        base = {
            "graph": graph,
            "thread_id": thread_id(state),
            "ticket_id": state.get("ticket_id"),
            "department_id": state.get("department_id"),
            "node": node,
            "agent": agent(state) if callable(agent) else agent,
            "input": summarize({key: state.get(key) for key in input_keys if key in state}),
            "started_at": started,
        }
        try:
            update = fn(state) or {}
        except Exception as exc:
            entry = {
                **base,
                "status": "interrupted" if _is_interrupt(exc) else "error",
                "output": summarize({"waiting_for": _interrupt_value(exc)} if _is_interrupt(exc) else {"error": f"{type(exc).__name__}: {exc}"}),
                "finished_at": utc_iso(),
                "duration_ms": int((time.perf_counter() - clock) * 1000),
            }
            sink.record(entry)
            raise
        entry = {
            **base,
            "status": "ok",
            "output": summarize({k: v for k, v in update.items() if k != "trace"}),
            "finished_at": utc_iso(),
            "duration_ms": int((time.perf_counter() - clock) * 1000),
        }
        sink.record(entry)
        return {**update, "trace": [*(update.get("trace") or []), entry]}

    run.__name__ = node
    return run


def runner_entry(
    *,
    graph: str,
    node: str,
    agent: str,
    ticket_id: int | None,
    department_id: str | None = None,
    input: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    started_at: str | None = None,
    status: str = "ok",
) -> dict[str, Any]:
    """Entrada de traza para los grafos de las Partes 1 y 2 (las registra su runner al recibir cada paso)."""
    finished = utc_iso()
    return {
        "graph": graph,
        "thread_id": None,
        "ticket_id": ticket_id,
        "department_id": department_id,
        "node": node,
        "agent": agent,
        "status": status,
        "input": summarize(input or {}),
        "output": summarize(output or {}),
        "started_at": started_at or finished,
        "finished_at": finished,
        "duration_ms": None,
    }


def record_safely(store: Any, entry: dict[str, Any]) -> None:
    """Guarda una entrada en el almacén sin romper el pipeline si falla."""
    if entry.get("ticket_id") is None or not hasattr(store, "append_trace"):
        return
    try:
        store.append_trace(entry["ticket_id"], entry)
    except Exception:  # pragma: no cover - la traza nunca rompe el flujo
        import logging

        logging.getLogger("rfp_intake.trace").exception("No se pudo guardar la traza de %s", entry.get("node"))
