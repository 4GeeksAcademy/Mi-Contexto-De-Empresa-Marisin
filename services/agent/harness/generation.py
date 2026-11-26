"""Llamadas de generación del agente de CX, siempre con el prompt seguro y el contexto aislado.

* `generate_answer` — respuesta de dominio sobre los chunks recuperados.
  Sanitiza los chunks (`isolation.sanitize_context`) antes de construir los
  mensajes: el texto externo nunca llega "en crudo" al modelo.

El small talk y la trivia **no pasan por el LLM**: los contesta el harness con
una plantilla de rechazo + reconducción (`responses.out_of_scope_reply`), así que
el modelo nunca puede responder conocimiento general («París») fuera de dominio.

Streaming (chat por WebSocket): solo si la corrida lo pide en
`config["configurable"]["stream_tokens"]` (lo pone `run_agent(on_token=...)`).
Entonces `_complete` itera `chat.completions.create(..., stream=True)`, emite cada
delta con el stream writer de LangGraph (modo `custom`) y, si se activa el
`cancel_event` de la corrida, cierra la respuesta HTTP del modelo
(`stream.close()`) y lanza `GenerationCancelled`: el abort es real, no se
ignoran tokens. Fuera de un grafo o sin `stream_tokens`, el camino es el de siempre.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from data.pipelines import rag as rag_pipeline

from . import isolation, prompts

logger = logging.getLogger("agent.harness.generation")

TokenWriter = Callable[[dict[str, Any]], None]


class GenerationCancelled(RuntimeError):
    """La corrida pidió abortar: la respuesta del modelo se cerró y no se emiten más tokens."""

    def __init__(self, *, tokens_streamed: int, stream_closed: bool):
        super().__init__(f"Generación cancelada tras {tokens_streamed} tokens (stream_closed={stream_closed})")
        self.tokens_streamed = tokens_streamed
        self.stream_closed = stream_closed


def _complete(
    messages: list[dict[str, str]],
    *,
    timeout: float | None = None,
    temperature: float | None = None,
    stream: bool = False,
    writer: TokenWriter | None = None,
    cancel_event: threading.Event | None = None,
) -> str:
    if stream and cancel_event is not None and cancel_event.is_set():
        raise GenerationCancelled(tokens_streamed=0, stream_closed=False)  # ni siquiera se llama al modelo
    settings = rag_pipeline.load_settings()
    rag_pipeline.check_models(settings)
    kwargs: dict[str, Any] = {"model": settings.llm_model, "messages": messages,
                              "temperature": rag_pipeline.TEMPERATURE if temperature is None else temperature}
    if timeout:
        kwargs["timeout"] = timeout
    if stream:
        return _complete_streaming(kwargs, writer=writer, cancel_event=cancel_event)
    completion = rag_pipeline.get_generation_client().chat.completions.create(**kwargs)
    return (completion.choices[0].message.content or "").strip()


def _delta_text(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None) or []
    delta = getattr(choices[0], "delta", None) if choices else None
    return (getattr(delta, "content", None) or "") if delta is not None else ""


def _complete_streaming(
    kwargs: dict[str, Any], *, writer: TokenWriter | None, cancel_event: threading.Event | None
) -> str:
    """Itera los deltas del modelo; con `cancel_event` activo cierra la respuesta y aborta."""
    response = rag_pipeline.get_generation_client().chat.completions.create(**kwargs, stream=True)
    parts: list[str] = []
    cancelled = False
    try:
        for chunk in response:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                response.close()  # corta la respuesta HTTP: el modelo deja de enviar tokens
                raise GenerationCancelled(tokens_streamed=len(parts), stream_closed=True)
            delta = _delta_text(chunk)
            if not delta:
                continue
            parts.append(delta)
            if writer is not None:
                writer({"token": delta})
    finally:
        close = getattr(response, "close", None)
        if not cancelled and callable(close):
            close()  # libera la conexión también si el modelo falla a mitad
    return "".join(parts).strip()


def _stream_options() -> tuple[TokenWriter, threading.Event | None] | None:
    """Writer y evento de cancelación si la corrida pidió tokens en vivo; si no, `None`."""
    try:
        from langgraph.config import get_config, get_stream_writer

        configurable = get_config().get("configurable") or {}
    except RuntimeError:  # fuera de un grafo (scripts, tests unitarios): sin streaming
        return None
    if not configurable.get("stream_tokens"):
        return None
    return get_stream_writer(), configurable.get("cancel_event")


def generate_answer(question: str, context: list[dict[str, Any]], country_lock: str | None = None) -> str:
    """Respuesta de dominio con el system prompt de CX y los documentos aislados."""
    safe_context = isolation.sanitize_context(context)
    messages = prompts.build_messages(question, safe_context, country_lock=country_lock)
    options = _stream_options()
    if options is None:
        answer = _complete(messages)
    else:
        writer, cancel_event = options
        answer = _complete(messages, stream=True, writer=writer, cancel_event=cancel_event)
    if not answer:
        raise RuntimeError("El modelo de generación devolvió una respuesta vacía")
    return answer
