"""Synthesizer: consolida las secciones en el resumen para Ventas y el handoff a la Parte 2.

La estructura de workstreams (qué pedir a quién) se arma de forma determinista
a partir de las secciones validadas; el LLM solo redacta el párrafo de resumen,
y ese párrafo también pasa por la guarda de cifras (si inventa un número, se
usa la plantilla).

Contradicciones (pregunta de diseño 4): el synthesizer **no las resuelve**, las
señala en `conflicts` para que Ventas (y el árbitro de la Parte 3) decidan:

- `volume-mismatch`: un worker cita un volumen mensual distinto del de los metadatos
  o de otro worker.
- `excluded-service-active`: un departamento activo cuyo servicio la RFP excluye
  explícitamente (no debería pasar: lo impide el orquestador).
- `currency-unknown`: sin país no hay moneda (BRIEFING §5); Ventas debe confirmarla.

El payload es el contrato `trackflow.rfp_intake.handoff/v1`
(`docs/rfp-intake/rfp-intake-design.md` §6): la Parte 2 arranca con él, sin
volver a leer el PDF.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from . import config
from .llm import LLM, resolve
from .schemas import DepartmentSection, RfpMetadata
from .text import fold, unanchored_numbers

logger = logging.getLogger("rfp_intake.synthesizer")

MAX_SUMMARY_CHARS = 900

SYSTEM_PROMPT = """Eres el synthesizer del análisis de RFPs de TrackFlow. Escribe para el equipo de Ventas de Miguel Torres
un resumen de 3 a 5 frases en español: quién es el cliente, qué pide, en qué moneda se cotiza, qué departamento
hace qué (nombra a cada responsable) y qué datos faltan. Usa SOLO los datos que recibes; no añadas cifras.
Responde solo con el texto del resumen, sin títulos ni viñetas."""

_VOLUME_NEAR = re.compile(r"(\d[\d.,]*)\s*(?:pedidos|orders|envios|shipments|packages|paquetes)")


def _volumes(text: str) -> set[int]:
    values = set()
    for match in _VOLUME_NEAR.finditer(fold(text)):
        digits = re.sub(r"[.,]", "", match.group(1))
        if digits.isdigit():
            values.add(int(digits))
    return values


def detect_conflicts(metadata: RfpMetadata, sections: list[DepartmentSection], excluded_services: list[str]) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    by_department: dict[str, set[int]] = {}
    for section in sections:
        text = " ".join(f"{a.topic} {a.detail}" for a in section.key_aspects)
        by_department[section.department_id] = _volumes(text)
    mentioned = set().union(*by_department.values()) if by_department else set()
    expected = {metadata.monthly_volume} if metadata.monthly_volume is not None else set()
    if (expected and mentioned - expected) or (not expected and len(mentioned) > 1):
        conflicts.append(
            {
                "type": "volume-mismatch",
                "detail": f"Volúmenes mensuales distintos: metadatos {sorted(expected) or '—'}, secciones "
                + ", ".join(f"{dept}={sorted(values)}" for dept, values in by_department.items() if values),
                "departments": [dept for dept, values in by_department.items() if values],
                "ask": config.COMMERCIAL_OWNER,
            }
        )
    for section in sections:
        service = config.DEPARTMENTS[section.department_id].service
        if service in excluded_services:
            conflicts.append(
                {
                    "type": "excluded-service-active",
                    "detail": f"{section.department_id} está activo, pero la RFP excluye «{service}».",
                    "departments": [section.department_id],
                    "ask": config.COMMERCIAL_OWNER,
                }
            )
    if metadata.currency is None:
        conflicts.append(
            {
                "type": "currency-unknown",
                "detail": "No se pudo determinar el país del cliente (EE. UU. → USD, España → EUR).",
                "departments": [section.department_id for section in sections],
                "ask": config.COMMERCIAL_OWNER,
            }
        )
    return conflicts


def _ask_line(section: DepartmentSection) -> str:
    topics = ", ".join(dict.fromkeys(a.topic for a in section.key_aspects if a.topic != "Requisito de la RFP"))
    base = f"Pedir a {section.responsible} ({section.department_name})"
    if topics:
        base += f": {topics}"
    else:
        base += ": revisar los requisitos de la RFP de su área"
    count = len(section.open_questions)
    if count:
        base += f" — {count} {'pregunta abierta' if count == 1 else 'preguntas abiertas'} para el cliente"
    return base + "."


def template_summary(metadata: RfpMetadata, sections: list[DepartmentSection], inactive: list[dict[str, str]]) -> str:
    client = metadata.client_name or "Cliente sin identificar"
    country = {"United States": "EE. UU.", "Spain": "España"}.get(metadata.client_country or "", "país sin confirmar")
    currency = metadata.currency or "moneda pendiente"
    services = {
        "warehousing": "almacenamiento", "last_mile": "última milla", "reverse_logistics": "devoluciones",
    }
    names = [services[s] for s in metadata.services_requested]
    requested = (" y ".join([", ".join(names[:-1]), names[-1]]) if len(names) > 1 else (names[0] if names else "servicios sin identificar"))
    parts = [f"{client} ({country}) pide {requested}; se cotiza en {currency}."]
    if sections:
        parts.append("Responsables: " + "; ".join(f"{s.responsible} ({s.department_id})" for s in sections) + ".")
    if inactive:
        parts.append("Sin participación: " + ", ".join(f"{i['department_id']} ({i['reason']})" for i in inactive) + ".")
    questions = sum(len(s.open_questions) for s in sections)
    if questions:
        parts.append(
            "Hay 1 dato que pedir al cliente antes de cotizar." if questions == 1
            else f"Hay {questions} datos que pedir al cliente antes de cotizar."
        )
    if metadata.deadline:
        parts.append(f"Fecha límite: {metadata.deadline.isoformat()}.")
    elif metadata.deadline_text:
        parts.append(f"Plazo indicado: «{metadata.deadline_text}».")
    return " ".join(parts)


def _llm_summary(payload: dict[str, Any], sources: str, llm: LLM | None, fallback: str) -> tuple[str, str]:
    try:
        text = resolve(llm)(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False, default=str)).strip()
    except Exception as exc:
        logger.warning("Resumen del synthesizer sin LLM (%s): plantilla", type(exc).__name__)
        return fallback, "rules"
    responsibles = [d["responsible"] for d in payload["departments"]]
    # Los conteos pequeños («2 departamentos», «3 preguntas») no son cifras de la RFP.
    invented = {n for n in unanchored_numbers(text, sources) if not (n.isdigit() and int(n) <= 10)}
    if (
        not text
        or len(text) > MAX_SUMMARY_CHARS
        or invented
        or any(name not in text for name in responsibles)
    ):
        logger.info("Resumen del LLM descartado por las guardas: plantilla")
        return fallback, "rules"
    return text, "llm"


def synthesize(
    *,
    ticket_id: int | None,
    rfp_id: str | None,
    metadata: RfpMetadata,
    sections: list[DepartmentSection],
    inactive_departments: list[dict[str, str]],
    unassigned_requests: list[dict[str, str]],
    excluded_services: list[str],
    readability: dict[str, Any] | None,
    llm: LLM | None = None,
) -> dict[str, Any]:
    ordered = sorted(sections, key=lambda s: config.DEPARTMENT_ORDER.index(s.department_id))
    departments = [
        {
            "department_id": section.department_id,
            "department_name": section.department_name,
            "responsible": section.responsible,
            "ask": _ask_line(section),
            "key_aspects": [aspect.model_dump() for aspect in section.key_aspects],
            "open_questions": list(section.open_questions),
        }
        for section in ordered
    ]
    conflicts = detect_conflicts(metadata, ordered, excluded_services)
    fallback = template_summary(metadata, ordered, inactive_departments)
    sources = json.dumps(
        {"metadata": metadata.model_dump(mode="json"), "departments": departments}, ensure_ascii=False
    )
    summary, summary_source = _llm_summary(
        {
            "client": metadata.model_dump(mode="json", exclude={"warnings", "source"}),
            "departments": departments,
            "inactive_departments": inactive_departments,
            "unassigned_requests": unassigned_requests,
        },
        sources,
        llm,
        fallback,
    )
    return {
        "contract": config.HANDOFF_CONTRACT,
        "ticket_id": ticket_id,
        "rfp_id": rfp_id,
        "next_status": config.NEXT_STATUS,
        "ready_for_drafting": bool(departments),
        "client": {
            "name": metadata.client_name,
            "reference": metadata.client_reference,
            "country": metadata.client_country,
            "currency": metadata.currency,
            "contact": metadata.contact.model_dump(),
        },
        "services_requested": list(metadata.services_requested),
        "monthly_volume": metadata.monthly_volume,
        "deadline": metadata.deadline.isoformat() if metadata.deadline else None,
        "deadline_text": metadata.deadline_text,
        "budget_range": metadata.budget_range,
        "departments": departments,
        "inactive_departments": inactive_departments,
        "unassigned_requests": unassigned_requests,
        "conflicts": conflicts,
        "summary": summary,
        "summary_source": summary_source,
        "readability": readability,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
