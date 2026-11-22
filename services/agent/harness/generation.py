"""Llamadas de generación del agente de CX, siempre con el prompt seguro y el contexto aislado.

* `generate_answer` — respuesta de dominio sobre los chunks recuperados.
  Sanitiza los chunks (`isolation.sanitize_context`) antes de construir los
  mensajes: el texto externo nunca llega "en crudo" al modelo.

El small talk y la trivia **no pasan por el LLM**: los contesta el harness con
una plantilla de rechazo + reconducción (`responses.out_of_scope_reply`), así que
el modelo nunca puede responder conocimiento general («París») fuera de dominio.
"""

from __future__ import annotations

import logging
from typing import Any

from data.pipelines import rag as rag_pipeline

from . import isolation, prompts

logger = logging.getLogger("agent.harness.generation")

def _complete(messages: list[dict[str, str]], *, timeout: float | None = None, temperature: float | None = None) -> str:
    settings = rag_pipeline.load_settings()
    rag_pipeline.check_models(settings)
    kwargs: dict[str, Any] = {"model": settings.llm_model, "messages": messages,
                              "temperature": rag_pipeline.TEMPERATURE if temperature is None else temperature}
    if timeout:
        kwargs["timeout"] = timeout
    completion = rag_pipeline.get_generation_client().chat.completions.create(**kwargs)
    return (completion.choices[0].message.content or "").strip()


def generate_answer(question: str, context: list[dict[str, Any]], country_lock: str | None = None) -> str:
    """Respuesta de dominio con el system prompt de CX y los documentos aislados."""
    safe_context = isolation.sanitize_context(context)
    answer = _complete(prompts.build_messages(question, safe_context, country_lock=country_lock))
    if not answer:
        raise RuntimeError("El modelo de generación devolvió una respuesta vacía")
    return answer
