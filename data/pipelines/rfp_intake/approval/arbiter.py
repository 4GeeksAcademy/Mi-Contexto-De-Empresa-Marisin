"""Nodo de arbitraje: resuelve los conflictos con el árbitro fijo y la regla del BRIEFING §7.

No hay un LLM «votando» entre agentes ni consenso: cada trigger tiene un árbitro
nombrado y una regla determinista, y la decisión queda firmada por ese árbitro
(`mode = "rule"`) en `ArbitrationDecision`:

| Trigger | Árbitro | Acción mientras quedan rondas | Agotado el límite |
|---|---|---|---|
| `volume-vs-capacity` | Miguel Torres | `request_changes` a lastmile con el volumen limitado a la capacidad de warehouse | rechazar lastmile |
| `returns-sla-breach` | Sofía Ramos (su sección) / Miguel Torres (otra sección) | `request_changes` forzado | rechazar (sin documento final) |
| `currency-mismatch` | Miguel Torres | reescribir en la moneda del país | rechazar |

Sin país confirmado no hay moneda a la que reescribir: el arbitraje queda
`blocked` hasta que Miguel Torres confirme el país (no se inventa).
`MAX_ARBITRATION_ROUNDS` limita cuántas veces se reabre una sección por conflicto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..drafting import pricing
from . import config
from .schemas import ArbitrationDecision, Conflict, ForcedChange
from .trace import utc_iso

COUNTRY_BY_CURRENCY = {"USD": "Estados Unidos", "EUR": "España"}


@dataclass
class Arbitration:
    decisions: list[dict[str, Any]] = field(default_factory=list)
    forced: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # department_id → ForcedChange
    rejected: dict[str, str] = field(default_factory=dict)  # department_id → motivo
    blocked: list[str] = field(default_factory=list)  # motivos sin resolución automática
    overrides: dict[str, dict[str, Any]] = field(default_factory=dict)  # department_id → contexto corregido


def _thousands(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _feedback(conflict: Conflict, arbiter: str) -> tuple[str, dict[str, Any]]:
    head = f"Árbitro {arbiter} (BRIEFING §7, {conflict.trigger}): "
    if conflict.trigger == config.TRIGGER_VOLUME_CAPACITY:
        capacity = int(conflict.data["capacity"])
        return (
            head + f"el almacén prepara como máximo {_thousands(capacity)} pedidos al mes. Cotiza para "
            f"{_thousands(capacity)} pedidos al mes (no {_thousands(int(conflict.data['assumed_volume']))}) y revisa "
            "a la baja el volumen y el costo, con el tramo de descuento que corresponda a ese volumen.",
            {"monthly_volume": capacity},
        )
    if conflict.trigger == config.TRIGGER_RETURNS_SLA:
        return (
            head + "nunca prometas procesar devoluciones en menos de 48 horas. El plazo de TrackFlow es de "
            f"{pricing.RETURNS_PROCESSING_HOURS} horas desde que la devolución llega al almacén; corrige o elimina la frase.",
            {},
        )
    expected = conflict.data.get("expected")
    return (
        head + f"el cliente es de {COUNTRY_BY_CURRENCY.get(expected, 'su país')}: reescribe todos los precios en "
        f"{expected} con el tarifario de {expected} y no cites ninguna otra moneda.",
        {},
    )


def _arbiter_for(conflict: Conflict, department_id: str) -> str:
    if conflict.trigger == config.TRIGGER_RETURNS_SLA and department_id != "reverse":
        return config.COMMERCIAL_DIRECTOR  # la promesa está embebida en otra sección
    return config.ARBITERS[conflict.trigger]


def arbitrate(conflicts: list[Conflict | dict[str, Any]], *, round_number: int,
              max_rounds: int = config.MAX_ARBITRATION_ROUNDS) -> Arbitration:
    """Aplica la regla fija de cada conflicto. `round_number` empieza en 1."""
    result = Arbitration()
    decided_at = utc_iso()
    for raw in conflicts:
        conflict = raw if isinstance(raw, Conflict) else Conflict.model_validate(raw)
        groups: dict[str, list[str]] = {}
        for department_id in conflict.departments:
            groups.setdefault(_arbiter_for(conflict, department_id), []).append(department_id)
        for arbiter, departments in groups.items():
            rule = config.RESOLUTION_RULES[conflict.trigger]
            if conflict.trigger == config.TRIGGER_CURRENCY and conflict.data.get("expected") is None:
                action = "blocked"
                result.blocked.append(f"{conflict.trigger}: {arbiter} tiene que confirmar el país del cliente")
            elif round_number > max_rounds:
                action = "reject"
                for department_id in departments:
                    result.rejected[department_id] = (
                        f"{conflict.trigger} sin resolver tras {max_rounds} rondas de arbitraje ({arbiter})"
                    )
            else:
                action = "request_changes"
                feedback, overrides = _feedback(conflict, arbiter)
                for department_id in departments:
                    change = ForcedChange(trigger=conflict.trigger, arbiter=arbiter, feedback=feedback,
                                          context_overrides=overrides)
                    result.forced.setdefault(department_id, []).append(change.model_dump())
                    if overrides:
                        result.overrides.setdefault(department_id, {}).update(overrides)
            result.decisions.append(
                ArbitrationDecision(
                    trigger=conflict.trigger, arbiter=arbiter, rule=rule, round=round_number, action=action,
                    departments=departments, detail=conflict.detail, data=conflict.data, decided_at=decided_at,
                ).model_dump()
            )
    return result
