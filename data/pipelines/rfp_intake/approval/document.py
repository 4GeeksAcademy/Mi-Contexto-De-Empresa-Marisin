"""Ultimate document synthesizer: consolida las secciones aprobadas en el documento final.

Se ejecuta solo cuando todas las secciones activas tienen `approval_status =
aprobada` y el detector ya no encuentra conflictos (BRIEFING §6). Es
determinista: no reescribe nada de lo que aprobaron los responsables, solo lo
ordena (warehouse → lastmile → reverse) y añade la cabecera, el registro de
aprobaciones (quién, cuándo, en cuántas rondas), los arbitrajes y los KPIs del
BRIEFING §3 (tiempo de aprobación por departamento y tiempo de armado).

`FinalDocument` (§2.3) = `ticket_id`, `sections`, `currency`, `generated_at`;
`markdown` es lo que se entrega a Ventas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .. import config as intake_config
from . import config
from .schemas import FinalDocument, FinalSection, SignoffEvent
from .trace import utc_iso

COUNTRY_LABELS = {"United States": "EE. UU.", "Spain": "España"}
ACTION_LABELS = {"request_changes": "reescritura forzada", "reject": "rechazo", "blocked": "bloqueado"}


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _minutes(start: Any, end: Any) -> float | None:
    a, b = _parse(start), _parse(end)
    if a is None or b is None:
        return None
    if (a.tzinfo is None) != (b.tzinfo is None):
        a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
    return round((b - a).total_seconds() / 60, 2)


def _hours(start: Any, end: Any) -> float | None:
    minutes = _minutes(start, end)
    return None if minutes is None else round(minutes / 60, 2)


def render_markdown(document: dict[str, Any]) -> str:
    client = document.get("client_name") or "Cliente sin identificar"
    country = COUNTRY_LABELS.get(document.get("client_country") or "", document.get("client_country") or "—")
    lines = [
        f"# Propuesta económica de TrackFlow para {client}",
        "",
        f"**Cliente:** {client} ({country}) · **Moneda:** {document.get('currency') or '—'} · "
        f"**Ticket:** #{document.get('ticket_id')} · **RFP:** `{document.get('rfp_id') or '—'}`",
        f"**Generado:** {document['generated_at']} · **Para:** {document['delivered_to']}",
        "",
        "Documento consolidado automáticamente tras el visto bueno de cada responsable de departamento "
        "(BRIEFING §6). Cada sección se reproduce tal y como la aprobó su responsable.",
    ]
    for section in document["sections"]:
        lines += ["", "---", "", section["content"].strip(), "",
                  f"> ✅ Aprobada por **{section['approver']}** ({section['department_name']}) el {section['approved_at']}."]
    lines += ["", "---", "", "## Registro de aprobaciones", "",
              "| Departamento | Responsable | Estado | Aprobada el | Rondas de revisión | Tiempo de aprobación (min) |",
              "|---|---|---|---|---|---|"]
    for section in document["sections"]:
        minutes = section.get("approval_minutes")
        lines.append(
            f"| {section['department_name']} | {section['approver']} | {section['approval_status']} | "
            f"{section['approved_at']} | {section['approval_rounds']} | {'—' if minutes is None else minutes} |"
        )
    arbitrations = document.get("arbitrations") or []
    if arbitrations:
        lines += ["", "## Arbitrajes (BRIEFING §7)", "", "| Ronda | Trigger | Árbitro | Acción | Secciones | Detalle |",
                  "|---|---|---|---|---|---|"]
        for item in arbitrations:
            lines.append(
                f"| {item['round']} | `{item['trigger']}` | {item['arbiter']} | "
                f"{ACTION_LABELS.get(item['action'], item['action'])} | {', '.join(item['departments'])} | {item['detail']} |"
            )
    metrics = document.get("metrics") or {}
    if metrics.get("proposal_hours") is not None:
        lines += ["", f"_Tiempo de armado de la propuesta (KPI §3): {metrics['proposal_hours']} h desde la carga de la RFP._"]
    return "\n".join(lines).strip() + "\n"


def build_final_document(
    *,
    ticket_id: int | None,
    rfp_id: str | None,
    client: dict[str, Any],
    currency: str | None,
    signoffs: dict[str, dict[str, Any]],
    arbitrations: list[dict[str, Any]],
    created_at: Any = None,
) -> dict[str, Any]:
    """`FinalDocument` validado. Lanza `ValueError` si alguna sección no está aprobada."""
    sections = []
    for department_id in intake_config.DEPARTMENT_ORDER:
        if department_id not in signoffs:
            continue
        event = SignoffEvent.model_validate(signoffs[department_id])
        if event.approval_status != config.APPROVAL_APPROVED:
            raise ValueError(f"La sección de {department_id} no está aprobada: no hay documento final.")
        department = intake_config.DEPARTMENTS[department_id]
        sections.append(
            FinalSection(
                department_id=department_id, department_name=department.name, responsible=department.responsible,
                approval_status=config.APPROVAL_APPROVED, approver=event.approver, approved_at=event.decided_at,
                approval_rounds=event.rounds, approval_minutes=_minutes(event.approval_requested_at, event.decided_at),
                draft_status=event.draft_status, content=event.draft_content,
            )
        )
    if not sections:
        raise ValueError("No hay secciones aprobadas.")
    generated_at = utc_iso()
    minutes = [s.approval_minutes for s in sections if s.approval_minutes is not None]
    data = {
        "ticket_id": ticket_id, "rfp_id": rfp_id, "client_name": client.get("name"),
        "client_country": client.get("country"), "currency": currency,
        "sections": [s.model_dump() for s in sections], "arbitrations": arbitrations,
        "metrics": {
            "sections": len(sections),
            "approval_minutes": {s.department_id: s.approval_minutes for s in sections},
            "max_approval_minutes": max(minutes) if minutes else None,
            "approval_rounds": sum(s.approval_rounds for s in sections),
            "arbitrations": len(arbitrations),
            "proposal_hours": _hours(created_at, generated_at),
        },
        "generated_at": generated_at,
        "delivered_to": f"Ventas ({config.COMMERCIAL_DIRECTOR})",
    }
    data["markdown"] = render_markdown(data)
    return FinalDocument.model_validate(data).model_dump()
