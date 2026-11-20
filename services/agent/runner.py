"""Ejecución de una corrida del agente: invoca el grafo compilado y guarda su trace.

`run_agent()` es lo único que usa el endpoint. Cada corrida tiene un `run_id`
(UUID) que también es el `thread_id` del checkpointer, de modo que el trace,
los checkpoints y la respuesta de la API se relacionan con el mismo id.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .tracing import TraceRecorder, jsonable, recording, save_trace, summarize_state, utc_now

logger = logging.getLogger("agent.runner")


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    status: str
    answer: str
    trace_path: Path


class AgentRunError(RuntimeError):
    """Un nodo del grafo falló. El trace de la corrida ya está guardado."""

    def __init__(self, run_id: str, failed_node: str | None):
        super().__init__(f"La corrida {run_id} falló en el nodo {failed_node or 'desconocido'}")
        self.run_id = run_id
        self.failed_node = failed_node


def run_config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


def checkpoint_summary(graph, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Checkpoints del hilo en orden cronológico: paso, origen, siguiente nodo y estado."""
    try:
        snapshots = list(graph.get_state_history(config))
    except Exception:
        logger.exception("No se pudo leer el historial de checkpoints")
        return []
    summary = []
    for snapshot in reversed(snapshots):  # get_state_history devuelve el más reciente primero
        metadata = snapshot.metadata or {}
        summary.append(
            {
                "checkpoint_id": snapshot.config.get("configurable", {}).get("checkpoint_id"),
                "step": metadata.get("step"),
                "source": metadata.get("source"),
                "next": list(snapshot.next),
                "values": summarize_state(snapshot.values),
            }
        )
    return summary


def build_trace(
    recorder: TraceRecorder,
    *,
    graph_name: str,
    final_state: dict[str, Any] | None,
    checkpoints: list[dict[str, Any]],
    error: BaseException | None,
) -> dict[str, Any]:
    final_state = final_state or {}
    return {
        "run_id": recorder.run_id,
        "thread_id": recorder.run_id,
        "graph": graph_name,
        "question": recorder.question,
        "started_at": recorder.started_at,
        "finished_at": utc_now(),
        "status": "error" if error else final_state.get("status", "unknown"),
        "path": recorder.path,
        "events": recorder.events,
        "checkpoints": checkpoints,
        "answer": final_state.get("answer"),
        "failed_node": recorder.failed_node if error else None,
        "error": jsonable({"type": type(error).__name__, "message": str(error)[:500]}) if error else None,
    }


def run_agent(question: str, *, graph=None, trace_directory: str | Path | None = None) -> AgentResult:
    """Invoca el grafo para `question`, guarda el trace y devuelve el resultado.

    Si un nodo falla, el trace se guarda igualmente (con `status = "error"` y el
    nodo que falló) y se lanza `AgentRunError` con el `run_id`.
    """
    if graph is None:
        from .graph import AGENT_GRAPH  # compilado al importar el módulo

        graph = AGENT_GRAPH
    run_id = str(uuid.uuid4())
    config = run_config(run_id)
    recorder = TraceRecorder(run_id=run_id, question=question)
    final_state: dict[str, Any] | None = None
    error: BaseException | None = None

    with recording(recorder):
        try:
            final_state = graph.invoke({"question": question}, config)
        except Exception as exc:
            error = exc

    trace = build_trace(
        recorder,
        graph_name=getattr(graph, "name", None) or "agent",
        final_state=final_state,
        checkpoints=checkpoint_summary(graph, config),
        error=error,
    )
    path = save_trace(trace, trace_directory)
    logger.info("agent run_id=%s status=%s path=%s", run_id, trace["status"], " → ".join(trace["path"]))

    if error is not None:
        logger.error("agent run_id=%s falló en %s: %r", run_id, trace["failed_node"], error)
        raise AgentRunError(run_id, trace["failed_node"]) from error
    return AgentResult(run_id=run_id, status=trace["status"], answer=trace["answer"] or "", trace_path=path)
