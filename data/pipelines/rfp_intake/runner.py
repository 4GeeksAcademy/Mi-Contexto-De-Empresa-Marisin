"""Ejecuta el grafo `rfp_intake` sobre un ticket y persiste cada paso.

`process_ticket()` es lo que dispara el router en segundo plano (y
`scripts/rfp_intake_run.py --ticket-id` para reprocesar a mano):

1. `start_processing`: deja el ticket en `analizando` / `convirtiendo` y borra
   cualquier análisis anterior (reprocesar es idempotente).
2. Recorre el grafo con `stream_mode="updates"` y guarda lo que emite cada nodo
   **en cuanto termina**: Markdown, clasificación, metadatos y métricas, una
   sección por worker y, al final, el handoff.
3. Estado final: `descartado` (lo decidió el clasificador), `analisis_completo`
   (terminó el synthesizer) o, si algo falla, sigue en `analizando` con
   `stage = error`, `error_stage` y `error_message`: el ticket nunca dice que
   terminó cuando no terminó, y la UI muestra en qué etapa se rompió.

Cada ticket corre en su propia tarea: un fallo o un descarte no afecta a otros.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import config
from .intake import resolve_pdf_path
from .llm import LLM
from .store import InMemoryRfpStore, RfpStore, TicketNotFound

logger = logging.getLogger("rfp_intake.runner")


@dataclass
class RunResult:
    ticket_id: int
    outcome: str  # "discarded" | "analysis_complete" | "error"
    stage: str
    duration_ms: int
    error: str | None = None
    nodes: list[str] = field(default_factory=list)


def process_ticket(ticket_id: int, store: RfpStore, *, llm: LLM | None = None, graph=None) -> RunResult:
    from .graph import build_graph

    started = time.perf_counter()
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        raise TicketNotFound(ticket_id)
    store.start_processing(ticket_id)
    stage = config.STAGE_CONVERTING
    executed: list[str] = []
    expected_sections = 0
    saved_sections = 0
    outcome = "error"
    initial = {
        "ticket_id": ticket_id,
        "rfp_id": ticket["rfp_id"],
        "pdf_path": str(resolve_pdf_path(ticket["raw_pdf_path"])),
        "sections": [],
    }
    try:
        compiled = graph or build_graph(llm)
        for update in compiled.stream(initial, stream_mode="updates"):
            for node, output in (update or {}).items():
                output = output or {}
                executed.append(node)
                if node == "convert_document":
                    store.save_markdown(ticket_id, output["markdown"])
                    stage = config.STAGE_CLASSIFYING
                    store.set_stage(ticket_id, stage)
                elif node == "classify_document":
                    accepted = output["classification"]["is_rfp"]
                    stage = config.STAGE_METADATA if accepted else config.STAGE_DISCARDED
                    store.save_classification(ticket_id, output["classification"], stage)
                elif node == "discard_document":
                    store.discard(ticket_id)
                    outcome = "discarded"
                elif node == "extract_metadata":
                    store.save_metadata(ticket_id, output["metadata"], output["readability"])
                    stage = config.STAGE_ORCHESTRATING
                elif node == "orchestrate":
                    expected_sections = len(output.get("workstreams") or [])
                    stage = config.STAGE_DEPARTMENTS if expected_sections else config.STAGE_SYNTHESIZING
                    store.set_stage(ticket_id, stage)
                elif node == "department_worker":
                    for section in output.get("sections") or []:
                        store.save_section(ticket_id, section)
                        saved_sections += 1
                    if saved_sections >= expected_sections:
                        stage = config.STAGE_SYNTHESIZING
                        store.set_stage(ticket_id, stage)
                elif node == "synthesize":
                    store.complete(ticket_id, output["handoff"])
                    stage = config.STAGE_DONE
                    outcome = "analysis_complete"
        if outcome == "error":
            raise RuntimeError("el grafo terminó sin descartar ni sintetizar")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        logger.exception("Ticket RFP %s falló en la etapa %s", ticket_id, stage)
        store.fail(ticket_id, stage, message)
        return RunResult(ticket_id, "error", stage, _elapsed(started), message, executed)
    result = RunResult(ticket_id, outcome, stage, _elapsed(started), None, executed)
    logger.info("Ticket RFP %s → %s en %d ms (%s)", ticket_id, outcome, result.duration_ms, " → ".join(executed))
    return result


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def process_ticket_safely(ticket_id: int, store: RfpStore, **kwargs: Any) -> None:
    """Entrada para `BackgroundTasks`: nunca deja escapar una excepción."""
    try:
        process_ticket(ticket_id, store, **kwargs)
    except Exception:  # p. ej. la BD caída antes de empezar
        logger.exception("No se pudo procesar el ticket RFP %s", ticket_id)


def run_file(pdf_path: Path | str, *, llm: LLM | None = None, store: RfpStore | None = None) -> dict[str, Any]:
    """Procesa un PDF local sin HTTP ni BD real (smoke run del CLI)."""
    path = Path(pdf_path).resolve()
    store = store or InMemoryRfpStore()
    content = path.read_bytes()
    ticket = store.create_ticket(
        rfp_id=str(uuid4()), raw_pdf_path=str(path), original_filename=path.name,
        file_sha256=hashlib.sha256(content).hexdigest(), file_size_bytes=len(content), uploaded_by="cli",
    )
    result = process_ticket(ticket["ticket_id"], store, llm=llm)
    final = store.get_ticket(ticket["ticket_id"]) or {}
    final["run"] = {"outcome": result.outcome, "duration_ms": result.duration_ms, "nodes": result.nodes, "error": result.error}
    return final
