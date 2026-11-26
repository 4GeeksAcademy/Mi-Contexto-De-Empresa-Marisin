"""Detección de los triggers de conflicto del BRIEFING §7 en estado estructurado.

Pregunta de diseño 3: el nodo de arbitraje solo es real si el disparador se
calcula con datos, no con la opinión de un agente sobre un texto libre. Cada
trigger se evalúa con reglas deterministas sobre las secciones del ticket y
devuelve un `Conflict` con las secciones ofensoras, la evidencia y las cifras:

- `volume-vs-capacity`: con `warehouse` y `lastmile` activos, el volumen mensual
  que asume `lastmile` (el del handoff de la Parte 1 —o el que fijó el árbitro— y
  cualquier «N pedidos/envíos al mes» que escriba su sección) supera la capacidad
  mensual del almacén que da servicio (`config.WAREHOUSE_MONTHLY_CAPACITY`).
- `returns-sla-breach`: alguna sección promete procesar devoluciones en menos de
  48 h (misma regla que el evaluador de cumplimiento de la Parte 2, ahora sobre
  todas las secciones a la vez, también las que un humano aprobó como provisionales).
- `currency-mismatch`: alguna sección cotiza en una moneda que no es la del país
  del cliente (US→USD, Spain→EUR), o dos secciones cotizan en monedas distintas.

Los agentes solo señalan: quien decide es el árbitro fijo (`arbiter.py`).
"""

from __future__ import annotations

import re
from typing import Any

from .. import config as intake_config
from ..drafting import config as drafting_config
from ..drafting import evaluators
from ..text import fold
from . import config
from .schemas import Conflict

# «5.000 pedidos al mes», «volumen de 30.000 envíos», «12000 orders per month».
_MONTHLY = re.compile(
    r"(\d[\d.,]*)\s*(?:pedidos|envios|paquetes|orders|shipments|packages)\s*(?:al|por|cada|/|a|per)\s*(?:mes|month)"
)
_VOLUME = re.compile(r"volumen[^.\n|]{0,40}?(\d[\d.,]*)\s*(?:pedidos|envios|paquetes|orders|shipments|packages)")
# Tramos de la tabla de descuentos o umbrales: no son el volumen que se asume.
_THRESHOLD_BEFORE = ("a partir de", "desde", "hasta", "mas de", "menos de", "tramo", "entre", "from", "up to", "over")


def _to_int(raw: str) -> int | None:
    digits = re.sub(r"[.,]", "", raw)
    return int(digits) if digits.isdigit() else None


_QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”")


def assumed_volumes(content: str) -> list[int]:
    """Volúmenes mensuales que una sección da por hechos.

    No cuentan los umbrales de la tabla de descuentos ni lo que cita entre comillas
    de la RFP («…30,000 orders a month…»): eso es lo que pide el cliente, no lo que
    la sección se compromete a mover.
    """
    folded = fold(_QUOTED.sub(" ", content or ""))
    values: list[int] = []
    for pattern in (_MONTHLY, _VOLUME):
        for match in pattern.finditer(folded):
            before = folded[max(0, match.start() - 25):match.start()]
            if any(word in before for word in _THRESHOLD_BEFORE):
                continue
            value = _to_int(match.group(1))
            if value is not None and value >= evaluators.SMALL_COUNT:
                values.append(value)
    return values


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _assumed(sections, department_id, monthly_volume, overrides) -> int | None:
    volume = ((overrides or {}).get(department_id) or {}).get("monthly_volume", monthly_volume)
    stated = assumed_volumes(sections[department_id].get("draft_content") or "")
    candidates = [v for v in [volume, *stated] if v is not None]
    return max(candidates) if candidates else None


def volume_vs_capacity(
    sections: dict[str, dict[str, Any]],
    *,
    currency: str | None,
    monthly_volume: int | None,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> Conflict | None:
    """Dispara cuando lastmile asume más pedidos de los que warehouse puede preparar.

    La regla del árbitro limita **la propuesta** a la capacidad: lastmile revisa
    volumen y costo a la baja y, si la sección de warehouse también cotiza un
    volumen por encima de su capacidad, se reescribe con el mismo límite (si no,
    el documento final diría dos volúmenes distintos).
    """
    if "warehouse" not in sections or "lastmile" not in sections or currency not in config.WAREHOUSE_MONTHLY_CAPACITY:
        return None
    capacity = config.WAREHOUSE_MONTHLY_CAPACITY[currency]
    assumed = _assumed(sections, "lastmile", monthly_volume, overrides)
    if assumed is None or assumed <= capacity:
        return None
    offenders = ["warehouse"] if (_assumed(sections, "warehouse", monthly_volume, overrides) or 0) > capacity else []
    offenders.append("lastmile")
    return Conflict(
        trigger=config.TRIGGER_VOLUME_CAPACITY,
        detail=(
            f"lastmile asume {_thousands(assumed)} pedidos al mes y el almacén de warehouse "
            f"({currency}) prepara como máximo {_thousands(capacity)}."
        ),
        departments=offenders,
        evidence=[f"volumen asumido por lastmile: {_thousands(assumed)}", f"capacidad de warehouse: {_thousands(capacity)}"],
        data={"assumed_volume": assumed, "capacity": capacity, "currency": currency},
    )


def returns_sla_breach(sections: dict[str, dict[str, Any]]) -> list[Conflict]:
    conflicts = []
    for department_id in intake_config.DEPARTMENT_ORDER:
        section = sections.get(department_id)
        if not section:
            continue
        violations = evaluators.check_returns_turnaround(section.get("draft_content") or "")
        if violations:
            conflicts.append(
                Conflict(
                    trigger=config.TRIGGER_RETURNS_SLA,
                    detail=f"La sección de {department_id} promete procesar devoluciones en menos de 48 horas.",
                    departments=[department_id],
                    evidence=[v.evidence for v in violations if v.evidence][:3],
                    data={"min_hours": drafting_config.MIN_RETURNS_HOURS},
                )
            )
    return conflicts


def currency_mismatch(sections: dict[str, dict[str, Any]], *, currency: str | None) -> Conflict | None:
    found = {
        department_id: sorted(evaluators.currencies_in(section.get("draft_content") or ""))
        for department_id, section in sections.items()
    }
    quoted = {code for codes in found.values() for code in codes}
    if currency is not None:
        offenders = [d for d in intake_config.DEPARTMENT_ORDER if d in found and set(found[d]) - {currency}]
        if not offenders:
            return None
        detail = f"El cliente se cotiza en {currency} y " + "; ".join(
            f"{d} cotiza en {', '.join(found[d])}" for d in offenders
        ) + "."
    else:
        if len(quoted) <= 1:
            return None
        offenders = [d for d in intake_config.DEPARTMENT_ORDER if found.get(d)]
        detail = "Sin país confirmado y las secciones cotizan en monedas distintas: " + "; ".join(
            f"{d}={', '.join(found[d])}" for d in offenders
        ) + "."
    return Conflict(
        trigger=config.TRIGGER_CURRENCY,
        detail=detail,
        departments=offenders,
        evidence=[f"{d}: {', '.join(found[d]) or '—'}" for d in intake_config.DEPARTMENT_ORDER if d in found],
        data={"expected": currency, "found": found},
    )


def detect_conflicts(
    sections: dict[str, dict[str, Any]],
    *,
    currency: str | None,
    monthly_volume: int | None,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> list[Conflict]:
    """Todos los triggers del BRIEFING §7 sobre las secciones actuales, en orden fijo."""
    conflicts: list[Conflict] = []
    volume = volume_vs_capacity(sections, currency=currency, monthly_volume=monthly_volume, overrides=overrides)
    if volume:
        conflicts.append(volume)
    conflicts += returns_sla_breach(sections)
    mismatch = currency_mismatch(sections, currency=currency)
    if mismatch:
        conflicts.append(mismatch)
    return conflicts
