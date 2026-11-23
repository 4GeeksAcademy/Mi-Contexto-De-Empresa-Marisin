"""Utilidades compartidas por los tests del flujo RFP (`data/pipelines/rfp_intake/`).

Los Markdown de `fixtures/rfp/` son la conversión con MarkItDown de los tres PDF
de muestra del BRIEFING (`rfp-requests/trackflow/`): formal (ModaViva, aceptar),
informal (Luna Cosmetics, aceptar) e inválido (pitch de RapidShip, rechazar).
Los PDF no se versionan: se suben por la UI (BRIEFING §4).
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "rfp"

FORMAL = "trackflow-request-1.md"
INFORMAL = "trackflow-request-2.md"
INVALID = "trackflow-request-3.md"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def offline_llm(system: str, user: str) -> str:
    raise RuntimeError("sin LLM en los tests")


class ScriptedLLM:
    """Doble del LLM: responde según el agente que llama (se reconoce por su system prompt)."""

    ROLES = (
        # Parte 2: generadores (antes que los workers: comparten el nombre del departamento).
        ("agente generador de Warehouse Operations", "draft_warehouse"),
        ("agente generador de Last Mile", "draft_lastmile"),
        ("agente generador de Reverse Logistics", "draft_reverse"),
        ("agente clasificador", "classifier"),
        ("agente de metadatos", "metadata"),
        ("orquestador", "orchestrator"),
        ("Warehouse Operations de TrackFlow", "warehouse"),
        ("Last Mile and Carrier Management de TrackFlow", "lastmile"),
        ("Reverse Logistics de TrackFlow", "reverse"),
        ("synthesizer", "synthesizer"),
    )

    def __init__(self, **responses):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def role(self, system: str) -> str:
        for marker, role in self.ROLES:
            if marker in system:
                return role
        raise AssertionError(f"system prompt desconocido: {system[:80]}")

    def __call__(self, system: str, user: str) -> str:
        role = self.role(system)
        self.calls.append((role, user))
        response = self.responses.get(role)
        if response is None:
            raise RuntimeError(f"sin respuesta para {role}")
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(user)
        return response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)

    def roles_called(self) -> list[str]:
        return [role for role, _ in self.calls]


def offline_handoff(fixture: str, ticket_id: int | None = None) -> dict:
    """Handoff de la Parte 1 (`trackflow.rfp_intake.handoff/v1`) sin LLM ni grafo, para la Parte 2."""
    from data.pipelines.rfp_intake import metadata, orchestrator, signals, synthesizer, workers
    from data.pipelines.rfp_intake.schemas import Workstream

    markdown = load(fixture)
    rfp_metadata = metadata.rules_metadata(markdown)
    plan = orchestrator.plan_workstreams(markdown, rfp_metadata, llm=offline_llm)
    sections = [
        workers.run_department_worker(Workstream.model_validate(w), rfp_metadata, llm=offline_llm)
        for w in plan["workstreams"]
    ]
    return synthesizer.synthesize(
        ticket_id=ticket_id, rfp_id=f"rfp-{fixture}", metadata=rfp_metadata, sections=sections,
        inactive_departments=plan["inactive_departments"], unassigned_requests=plan["unassigned_requests"],
        excluded_services=signals.detect_services(markdown).excluded, readability=None, llm=offline_llm,
    )


def ticket_ready_for_drafting(store, fixture: str) -> int:
    """Ticket en `analisis_completo` con secciones y handoff, como lo deja la Parte 1."""
    ticket = store.create_ticket(
        rfp_id=f"rfp-{fixture}", raw_pdf_path=f"data/raw/rfp/{fixture}.pdf", original_filename=fixture,
        file_sha256="0" * 64, file_size_bytes=100, uploaded_by="1",
    )
    ticket_id = ticket["ticket_id"]
    handoff = offline_handoff(fixture, ticket_id)
    for department in handoff["departments"]:
        store.save_section(ticket_id, {
            "department_id": department["department_id"], "department_name": department["department_name"],
            "responsible": department["responsible"], "key_aspects": department["key_aspects"],
            "open_questions": department["open_questions"], "excerpts": [], "source": "rules", "warnings": [],
        })
    store.complete(ticket_id, handoff)
    return ticket_id
