"""Ejecución de una corrida del agente: invoca el grafo compilado y guarda su trace.

`run_agent()` es lo único que usa el endpoint. Cada corrida tiene un `run_id`
(UUID) que también es el `thread_id` del checkpointer, de modo que el trace,
los checkpoints y la respuesta de la API se relacionan con el mismo id.

Memoria (Hito 8 · Parte 1): con `user`, la corrida pertenece a una conversación
(`conversation_id`, que se crea si no llega) y activa la memoria del agente. Sin
`user` (scripts de evals) la memoria no actúa y el grafo se comporta como antes.

Tokens en vivo (chat por WebSocket): con `on_token`, la corrida usa
`graph.stream(stream_mode=["custom", "values"])`, reenvía cada token que emite
`generate_answer` y comprueba `cancel_event` entre chunks. Si se cancela, el
generador se cierra (no se ejecutan más nodos), el trace queda `interrupted` y
se lanza `AgentRunCancelled`. Sin `on_token`, es el `graph.invoke` de siempre.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .harness import events as guard_events
from .harness.input_sanitizer import record_event as record_sanitization
from .harness.input_sanitizer import sanitize_user_input
from .memory.models import Actor
from .tracing import TraceRecorder, jsonable, recording, save_trace, summarize_state, utc_now

logger = logging.getLogger("agent.runner")
# Una línea JSON por corrida con la decisión del agente (NIST · trazabilidad); ver `decision_record`.
audit_logger = logging.getLogger("agent.audit")

# Qué fuente de datos consulta cada nodo: el trace lista las usadas, en orden.
SOURCE_BY_NODE = {"lookup_ticket": "incidents", "lookup_inventory": "inventory", "retrieve": "rag"}


def sources_used(path: list[str]) -> list[str]:
    return [SOURCE_BY_NODE[node] for node in path if node in SOURCE_BY_NODE]


@dataclass(frozen=True)
class AgentResult:
    run_id: str
    status: str
    answer: str
    trace_path: Path
    sources: tuple[str, ...] = ()
    conversation_id: str | None = None
    memory: dict[str, Any] = field(default_factory=dict)
    guardrail: dict[str, Any] | None = None


def memory_summary(final_state: dict[str, Any] | None) -> dict[str, Any]:
    """Qué hizo la memoria en la corrida: decisión, propuesta y notas recordadas."""
    final_state = final_state or {}
    summary = {
        "decision": final_state.get("memory_decision"),
        "proposal": final_state.get("memory_proposal"),
        "notes": final_state.get("memory_notes"),
    }
    return {key: value for key, value in summary.items() if value}


class AgentRunError(RuntimeError):
    """Un nodo del grafo falló. El trace de la corrida ya está guardado."""

    def __init__(self, run_id: str, failed_node: str | None):
        super().__init__(f"La corrida {run_id} falló en el nodo {failed_node or 'desconocido'}")
        self.run_id = run_id
        self.failed_node = failed_node


class AgentRunCancelled(RuntimeError):
    """La corrida se abortó a petición (`cancel_event`). El trace ya está guardado como `interrupted`."""

    def __init__(self, run_id: str, *, tokens_sent: int = 0, stream_closed: bool = False):
        super().__init__(f"La corrida {run_id} se canceló tras {tokens_sent} tokens")
        self.run_id = run_id
        self.tokens_sent = tokens_sent
        self.stream_closed = stream_closed


CANCELLED_ERROR = "GenerationCancelled"  # nombre de `harness.generation.GenerationCancelled` en el trace


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
    conversation_id: str | None = None,
    guardrail_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    final_state = final_state or {}
    trace = {
        "run_id": recorder.run_id,
        "thread_id": recorder.run_id,
        "graph": graph_name,
        "question": recorder.question,
        "started_at": recorder.started_at,
        "finished_at": utc_now(),
        "status": "error" if error else final_state.get("status", "unknown"),
        "path": recorder.path,
        "sources": sources_used(recorder.path),
        "route": final_state.get("route"),
        "events": recorder.events,
        "checkpoints": checkpoints,
        "answer": final_state.get("answer"),
        "failed_node": recorder.failed_node if error else None,
        "error": jsonable({"type": type(error).__name__, "message": str(error)[:500]}) if error else None,
    }
    if conversation_id:
        trace["conversation_id"] = conversation_id
        trace["memory"] = jsonable(memory_summary(final_state))
    guardrail = guardrail_summary(final_state)
    if guardrail or guardrail_events:
        trace["guardrail"] = guardrail
        trace["guardrail_events"] = jsonable(guardrail_events or [])
    return trace


def _tool_summary(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None
    return {key: result.get(key) for key in ("tool", "mcp_tool", "status", "total", "error") if result.get(key) is not None}


def decision_record(
    trace: dict[str, Any], final_state: dict[str, Any] | None, actor: Actor | None
) -> dict[str, Any]:
    """Qué acción tomó el agente y por qué (NIST · Detect/Respond: trazabilidad por corrida).

    Resume, sin el texto de la respuesta ni datos de terceros: quién preguntó (rol),
    qué decidió el enrutador (fuentes, quién lo decidió y su motivo), qué tools se
    llamaron y con qué resultado, qué guardrails saltaron y el estado final.
    """
    final_state = final_state or {}
    route = trace.get("route") or {}
    events = trace.get("guardrail_events") or []
    tools = [summary for summary in (
        _tool_summary(final_state.get("ticket_result")), _tool_summary(final_state.get("inventory_result")),
    ) if summary]
    return {
        "run_id": trace["run_id"],
        "at": trace.get("finished_at"),
        "actor_role": actor.role if actor else "internal",
        "status": trace.get("status"),
        "path": trace.get("path"),
        "sources": trace.get("sources"),
        "decided_by": route.get("decided_by"),
        "reason": (route.get("reason") or "")[:300] or None,
        "tool_calls": tools,
        "guardrail": trace.get("guardrail"),
        "guardrail_events": [
            {key: event.get(key) for key in ("guard", "category", "action", "rules") if event.get(key)}
            for event in events
        ],
        "failed_node": trace.get("failed_node"),
    }


def guardrail_summary(final_state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Veredicto del harness si la corrida se bloqueó o se recondujo (None si fue de dominio)."""
    guard = (final_state or {}).get("guardrail") or {}
    if guard.get("action") in (None, "allow"):
        return None
    return {key: guard.get(key) for key in ("category", "action", "failure_type", "rules") if guard.get(key)}


def stream_graph(
    graph,
    initial: dict[str, Any],
    config: dict[str, Any],
    on_token: Callable[[str], None],
    cancel_event: threading.Event | None,
    stats: dict[str, Any],
) -> dict[str, Any] | None:
    """Recorre el grafo reenviando tokens; devuelve el último estado (`values`).

    Comprueba `cancel_event` antes de cada chunk: un token que llegue después de
    activarse nunca se reenvía, y al salir del bucle el generador se cierra.
    """
    final_state: dict[str, Any] | None = None
    stream = graph.stream(initial, config, stream_mode=["custom", "values"])
    try:
        for mode, chunk in stream:
            if cancel_event is not None and cancel_event.is_set():
                stats["cancelled"] = True
                break
            if mode == "values":
                final_state = chunk
            elif mode == "custom" and isinstance(chunk, dict) and chunk.get("token"):
                stats["tokens_sent"] += 1
                on_token(chunk["token"])
    finally:
        stream.close()  # espera al nodo en curso, que aborta al ver el evento
    return final_state


def generation_stream_closed(recorder: TraceRecorder) -> bool:
    """El nodo de generación cerró la respuesta del modelo al cancelarse."""
    return any((event.get("error") or {}).get("type") == CANCELLED_ERROR for event in recorder.events)


def run_agent(
    question: str,
    *,
    conversation_id: str | None = None,
    user: dict[str, Any] | None = None,
    graph=None,
    trace_directory: str | Path | None = None,
    on_token: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> AgentResult:
    """Invoca el grafo para `question`, guarda el trace y devuelve el resultado.

    Si un nodo falla, el trace se guarda igualmente (con `status = "error"` y el
    nodo que falló) y se lanza `AgentRunError` con el `run_id`.

    Con `on_token`, cada token de la generación se entrega en vivo y
    `cancel_event` puede abortar la corrida: trace `interrupted` y `AgentRunCancelled`.
    """
    if graph is None:
        from .graph import AGENT_GRAPH  # compilado al importar el módulo

        graph = AGENT_GRAPH
    run_id = str(uuid.uuid4())
    config = run_config(run_id)
    # NIST · Protect: el grafo, el prompt y el trace trabajan con la pregunta saneada.
    raw_question = question
    sanitized = sanitize_user_input(question, record=False)
    question = sanitized.text
    recorder = TraceRecorder(run_id=run_id, question=question)
    final_state: dict[str, Any] | None = None
    error: BaseException | None = None
    stats: dict[str, Any] = {"tokens_sent": 0, "cancelled": False}
    if on_token is not None:
        config["configurable"].update({"stream_tokens": True, "cancel_event": cancel_event})

    initial: dict[str, Any] = {"question": question}
    actor = Actor.from_user(user)
    if actor is not None:
        conversation_id = conversation_id or str(uuid.uuid4())
        initial.update({"conversation_id": conversation_id, "run_id": run_id, "actor": actor.model_dump()})
    else:
        conversation_id = None

    with recording(recorder), guard_events.bind(
        run_id=run_id, conversation_id=conversation_id, user_id=actor.user_id if actor else None
    ) as collected_events:
        record_sanitization(sanitized, raw_question)
        try:
            if on_token is None:
                final_state = graph.invoke(initial, config)
            else:
                final_state = stream_graph(graph, initial, config, on_token, cancel_event, stats)
        except Exception as exc:
            if type(exc).__name__ == CANCELLED_ERROR and cancel_event is not None and cancel_event.is_set():
                stats["cancelled"] = True
            else:
                error = exc

    cancelled = bool(stats["cancelled"])
    trace = build_trace(
        recorder,
        graph_name=getattr(graph, "name", None) or "agent",
        final_state=final_state,
        checkpoints=checkpoint_summary(graph, config),
        error=error,
        conversation_id=conversation_id,
        guardrail_events=collected_events,
    )
    if cancelled:
        stream_closed = generation_stream_closed(recorder)
        trace["status"] = "interrupted"
        trace["cancelled"] = {"tokens_sent": stats["tokens_sent"], "stream_closed": stream_closed}
    trace["decision"] = jsonable(decision_record(trace, final_state, actor))
    audit_logger.info("agent_decision %s", json.dumps(trace["decision"], ensure_ascii=False, default=str))
    path = save_trace(trace, trace_directory)
    if cancelled:
        logger.info(
            "agent run_id=%s cancelled tokens_sent=%d stream_closed=%s path=%s",
            run_id, stats["tokens_sent"], stream_closed, " → ".join(trace["path"]),
        )
        raise AgentRunCancelled(run_id, tokens_sent=stats["tokens_sent"], stream_closed=stream_closed)
    logger.info("agent run_id=%s status=%s path=%s", run_id, trace["status"], " → ".join(trace["path"]))

    if error is not None:
        logger.error("agent run_id=%s falló en %s: %r", run_id, trace["failed_node"], error)
        raise AgentRunError(run_id, trace["failed_node"]) from error
    return AgentResult(
        run_id=run_id,
        status=trace["status"],
        answer=trace["answer"] or "",
        trace_path=path,
        sources=tuple(trace["sources"]),
        conversation_id=conversation_id,
        memory=trace.get("memory") or {},
        guardrail=trace.get("guardrail"),
    )
