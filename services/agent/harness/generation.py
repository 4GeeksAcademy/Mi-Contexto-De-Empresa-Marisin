"""Llamadas de generación del agente de CX, siempre con el prompt seguro y el contexto aislado.

* `generate_answer` — respuesta de dominio sobre los chunks recuperados.
  Sanitiza los chunks (`isolation.sanitize_context`) antes de construir los
  mensajes: el texto externo nunca llega "en crudo" al modelo.
* `small_talk_answer` — una frase breve para saludos/trivia. Si el LLM falla,
  hay una plantilla: la reconducción la añade siempre el harness, no el modelo.
"""

from __future__ import annotations

import logging
from typing import Any

from data.pipelines import rag as rag_pipeline

from . import isolation, prompts

logger = logging.getLogger("agent.harness.generation")

SMALL_TALK_TIMEOUT_SECONDS = 10.0
SMALL_TALK_FALLBACK = {
    "greeting": "¡Hola!",
    "how_are_you": "Todo bien por aquí, gracias.",
    "thanks": "¡De nada!",
    "time_weather": "No tengo acceso a la hora ni al tiempo en tiempo real.",
    "trivia": "Es una pregunta general que queda fuera de lo que atiendo.",
    "general_logistics": "Es un concepto general de logística; ahora no puedo darte una definición fiable.",
}
SMALL_TALK_MAX_CHARS = 280


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


def small_talk_answer(question: str, rules: list[str] | None = None, *, general_concept: bool = False) -> str:
    """Una o dos frases breves (small talk o concepto general de logística). Nunca lanza: si el LLM falla, plantilla."""
    try:
        messages = prompts.build_small_talk_messages(question, general_concept=general_concept)
        answer = _complete(messages, timeout=SMALL_TALK_TIMEOUT_SECONDS, temperature=0.3)
        if answer:
            return answer[:SMALL_TALK_MAX_CHARS]
    except Exception as exc:
        logger.info("Small talk sin LLM (%s): plantilla", type(exc).__name__)
    if general_concept:
        return SMALL_TALK_FALLBACK["general_logistics"]
    for rule in rules or []:
        if rule in SMALL_TALK_FALLBACK:
            return SMALL_TALK_FALLBACK[rule]
    return "¡Hola!"
