"""Nodos del grafo `rfp_intake`. Funciones puras: estado → actualización.

Ninguno escribe en la base de datos: `runner.py` persiste cada actualización a
medida que el grafo la emite (`stream_mode="updates"`), así el ticket refleja
en todo momento la última etapa terminada. El LLM llega por
`config["configurable"]["llm"]` (los tests inyectan un doble).
"""

from __future__ import annotations

from typing import Any

try:
    from langchain_core.runnables import RunnableConfig
except ImportError:  # pragma: no cover - langchain-core llega con langgraph
    RunnableConfig = dict  # type: ignore[misc,assignment]

from . import classifier, convert, metadata as metadata_agent, metrics, orchestrator, signals, synthesizer, workers
from .schemas import DepartmentSection, RfpMetadata, Workstream
from .state import RfpState, WorkerInput

# Agentes que leen el Markdown completo: clasificador, metadatos y orquestador.
FULL_DOCUMENT_READERS = 3


def _llm(config: RunnableConfig | None):
    if isinstance(config, dict):
        return (config.get("configurable") or {}).get("llm")
    return None


def convert_document(state: RfpState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """PDF de `data/raw/rfp/` → Markdown limpio (MarkItDown). Si ya hay Markdown, no reconvierte."""
    if state.get("markdown"):
        return {"markdown": state["markdown"]}
    return {"markdown": convert.pdf_to_markdown(state["pdf_path"])}


def classify_document(state: RfpState, config: RunnableConfig | None = None) -> dict[str, Any]:
    decision = classifier.classify_document(state["markdown"], llm=_llm(config))
    return {"classification": decision.model_dump(mode="json")}


def route_after_classification(state: RfpState) -> str:
    return "extract_metadata" if state["classification"]["is_rfp"] else "discard_document"


def discard_document(state: RfpState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Fin del flujo para lo que no es una RFP: el runner deja el ticket en `descartado`."""
    return {"outcome": "discarded"}


def extract_metadata(state: RfpState, config: RunnableConfig | None = None) -> dict[str, Any]:
    extracted = metadata_agent.extract_metadata(state["markdown"], llm=_llm(config))
    readability = metrics.readability_metrics(state["markdown"], llm_readers=FULL_DOCUMENT_READERS)
    return {"metadata": extracted.model_dump(mode="json"), "readability": readability}


def orchestrate(state: RfpState, config: RunnableConfig | None = None) -> dict[str, Any]:
    rfp_metadata = RfpMetadata.model_validate(state["metadata"])
    plan = orchestrator.plan_workstreams(state["markdown"], rfp_metadata, llm=_llm(config))
    return {
        "workstreams": plan["workstreams"],
        "inactive_departments": plan["inactive_departments"],
        "unassigned_requests": plan["unassigned_requests"],
        "orchestrator": {"source": plan["source"], "warnings": plan["warnings"]},
    }


def worker_inputs(state: RfpState) -> list[WorkerInput]:
    """Lo único que recibe cada worker: su workstream + los metadatos compartidos."""
    return [{"workstream": workstream, "metadata": state["metadata"]} for workstream in state.get("workstreams") or []]


def department_worker(state: WorkerInput, config: RunnableConfig | None = None) -> dict[str, Any]:
    section = workers.run_department_worker(
        Workstream.model_validate(state["workstream"]),
        RfpMetadata.model_validate(state["metadata"]),
        llm=_llm(config),
    )
    return {"sections": [section.model_dump(mode="json")]}


def synthesize(state: RfpState, config: RunnableConfig | None = None) -> dict[str, Any]:
    handoff = synthesizer.synthesize(
        ticket_id=state.get("ticket_id"),
        rfp_id=state.get("rfp_id"),
        metadata=RfpMetadata.model_validate(state["metadata"]),
        sections=[DepartmentSection.model_validate(section) for section in state.get("sections") or []],
        inactive_departments=state.get("inactive_departments") or [],
        unassigned_requests=state.get("unassigned_requests") or [],
        excluded_services=signals.detect_services(state["markdown"]).excluded,
        readability=state.get("readability"),
        llm=_llm(config),
    )
    return {"handoff": handoff, "outcome": "analysis_complete"}
