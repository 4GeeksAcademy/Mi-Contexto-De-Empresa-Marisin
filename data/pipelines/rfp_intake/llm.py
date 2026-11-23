"""Acceso al modelo de generación de 4Geeks para los agentes del flujo RFP.

Reutiliza la configuración del RAG (`LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL`):
mismo proveedor, ninguna variable nueva. Cada agente recibe un `LLM` —una
función `(system, user) -> texto`— para que los tests le pasen un doble; si no
recibe ninguno, usa `complete()`, que se busca en tiempo de llamada para que
`tests/conftest.py` pueda desconectarlo.
"""

from __future__ import annotations

from collections.abc import Callable

from . import config

LLM = Callable[[str, str], str]


def complete(system: str, user: str) -> str:
    """Una llamada a `/chat/completions` con temperatura 0. Devuelve el texto."""
    from data.pipelines import rag as rag_pipeline

    settings = rag_pipeline.load_settings()
    if not settings.llm_model:
        raise RuntimeError("Falta LLM_MODEL en .env (modelo de generación de 4Geeks).")
    completion = rag_pipeline.get_generation_client().chat.completions.create(
        model=settings.llm_model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        timeout=config.LLM_TIMEOUT_SECONDS,
    )
    content = (completion.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("El modelo devolvió una respuesta vacía")
    return content


def resolve(llm: LLM | None) -> LLM:
    # `complete` se lee del módulo en cada llamada: un monkeypatch lo sustituye.
    return llm if llm is not None else complete
