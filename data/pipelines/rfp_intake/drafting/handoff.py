"""Entrada y salida de la Parte 2: consume el handoff de la Parte 1 y arma el de la Parte 3.

- `validate_input()`: el ticket llega con `rfp_tickets.handoff` en el contrato
  `trackflow.rfp_intake.handoff/v1`, `ready_for_drafting` y al menos un
  departamento. Si no, `HandoffError`: la Parte 2 no improvisa un resumen
  paralelo ni vuelve al PDF.
- `drafting_inputs()`: un `DraftingInput` por departamento del handoff, con
  solo sus datos + su tarifa + sus políticas.
- `anchor_sources()`: textos contra los que el evaluador ancla cada cifra.
- `output_handoff()`: contrato `trackflow.rfp_drafting.handoff/v1` para la
  Parte 3, con cada sección (también las `needs_human_review`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from .. import config as intake_config
from . import config, knowledge, pricing
from .schemas import DraftingInput


class HandoffError(ValueError):
    pass


def validate_input(handoff: dict[str, Any] | None) -> dict[str, Any]:
    if not handoff:
        raise HandoffError("El ticket no tiene handoff de la Parte 1.")
    if handoff.get("contract") != config.INPUT_CONTRACT:
        raise HandoffError(f"Contrato de handoff desconocido: {handoff.get('contract')!r} (se espera {config.INPUT_CONTRACT}).")
    departments = handoff.get("departments") or []
    if not departments:
        raise HandoffError("El handoff no tiene departamentos activos: no hay secciones que redactar.")
    unknown = [d.get("department_id") for d in departments if d.get("department_id") not in intake_config.DEPARTMENTS]
    if unknown:
        raise HandoffError(f"Departamentos que no existen en el BRIEFING: {unknown}.")
    return handoff


def _department_conflicts(handoff: dict[str, Any], department_id: str) -> list[dict[str, Any]]:
    return [c for c in handoff.get("conflicts") or [] if department_id in (c.get("departments") or [])]


def drafting_inputs(handoff: dict[str, Any], *, knowledge_mode: str | None = None) -> list[DraftingInput]:
    client = handoff.get("client") or {}
    currency = client.get("currency")
    ordered = sorted(
        handoff.get("departments") or [], key=lambda d: intake_config.DEPARTMENT_ORDER.index(d["department_id"])
    )
    inputs = []
    for department in ordered:
        department_id = department["department_id"]
        inputs.append(
            DraftingInput(
                ticket_id=handoff.get("ticket_id"),
                department_id=department_id,
                department_name=department.get("department_name") or intake_config.DEPARTMENTS[department_id].name,
                responsible=intake_config.DEPARTMENTS[department_id].responsible,  # siempre del BRIEFING
                client_name=client.get("name"),
                client_reference=client.get("reference"),
                client_country=client.get("country"),
                currency=currency,
                services_requested=list(handoff.get("services_requested") or []),
                monthly_volume=handoff.get("monthly_volume"),
                deadline=handoff.get("deadline"),
                deadline_text=handoff.get("deadline_text"),
                budget_range=handoff.get("budget_range"),
                ask=department.get("ask") or "",
                key_aspects=[
                    {k: str(a.get(k, "")) for k in ("topic", "detail", "evidence")}
                    for a in department.get("key_aspects") or []
                ],
                open_questions=[str(q) for q in department.get("open_questions") or []],
                conflicts=_department_conflicts(handoff, department_id),
                reference=pricing.reference_text(department_id, currency) if currency in pricing.TARIFFS else "",
                knowledge=knowledge.snippets_for(department_id, knowledge_mode),
            )
        )
    return inputs


def anchor_sources(context: DraftingInput) -> list[str]:
    """Todo lo que el generador puede citar: datos del handoff, tarifario y políticas."""
    data = context.model_dump(mode="json", exclude={"reference", "knowledge"})
    sources = [json.dumps(data, ensure_ascii=False), context.reference or ""]
    sources += [snippet["text"] for snippet in context.knowledge]
    # Sin moneda no hay tarifario en el contexto, pero las condiciones fijas siguen valiendo.
    sources.append(pricing.discount_table())
    return sources


def output_handoff(
    *, ticket_id: int | None, input_handoff: dict[str, Any], sections: list[dict[str, Any]]
) -> dict[str, Any]:
    ordered = sorted(sections, key=lambda s: intake_config.DEPARTMENT_ORDER.index(s["department_id"]))
    review = [s["department_id"] for s in ordered if s["draft_status"] == config.SECTION_NEEDS_REVIEW]
    iterations = [s["iterations"] for s in ordered]
    first_pass = [s for s in ordered if s["iterations"] == 1 and s["draft_status"] == config.SECTION_PASSED]
    client = input_handoff.get("client") or {}
    return {
        "contract": config.OUTPUT_CONTRACT,
        "ticket_id": ticket_id,
        "rfp_id": input_handoff.get("rfp_id"),
        "next_status": config.NEXT_STATUS,
        "ready_for_approval": bool(ordered),
        "status": config.STATUS_NEEDS_REVIEW if review else config.STATUS_EVALUATING,
        "client": {"name": client.get("name"), "country": client.get("country"), "currency": client.get("currency")},
        "currency": client.get("currency"),
        "needs_human_review": review,
        "sections": [
            {
                "department_id": s["department_id"],
                "department_name": s["department_name"],
                "responsible": s["responsible"],
                "draft_status": s["draft_status"],
                "provisional": s["provisional"],
                "iterations": s["iterations"],
                "draft_source": s["draft_source"],
                "draft_content": s["draft_content"],
                "evaluation_result": s["evaluation_result"],
                # Historial por iteración sin los borradores intermedios (están en la BD).
                "evaluation_history": [
                    {k: v for k, v in entry.items() if k != "draft_content"} for entry in s.get("evaluation_history") or []
                ],
            }
            for s in ordered
        ],
        "conflicts": input_handoff.get("conflicts") or [],
        "metrics": {
            "max_iterations": config.MAX_ITERATIONS,
            "avg_iterations": round(mean(iterations), 2) if iterations else 0,
            "first_pass_sections": len(first_pass),
            "sections": len(ordered),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
