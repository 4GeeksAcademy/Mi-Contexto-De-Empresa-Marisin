"""Estado de los grafos `rfp_drafting` (ticket) y `rfp_section_loop` (un departamento).

Pregunta de diseño 2 — dos evaluadores en paralelo escribiendo en el estado
compartido: cada evaluador devuelve **solo su clave** dentro de `checks`
(`readability`, `relevance` o `compliance`) y el reductor `merge_checks` las
une sin pisarse; cada resultado lleva su `iteration` y el juez comprueba que
las tres son de la iteración en curso. `history` se acumula con suma (una
entrada por iteración) y `sections` igual en el grafo del ticket (una por
departamento en paralelo).
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_checks(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class SectionState(TypedDict, total=False):
    ticket_id: int | None
    department_id: str
    context: dict[str, Any]  # DraftingInput del departamento
    sources: list[str]  # anclas de cifras para el evaluador de cumplimiento
    max_iterations: int
    iteration: int
    draft: dict[str, Any]  # SectionDraft en curso
    checks: Annotated[dict[str, Any], merge_checks]
    evaluation: dict[str, Any]  # último EvaluationResult (con `pass`)
    history: Annotated[list[dict[str, Any]], operator.add]
    final: dict[str, Any]  # DraftedSection


class DraftingState(TypedDict, total=False):
    ticket_id: int | None
    handoff: dict[str, Any]  # trackflow.rfp_intake.handoff/v1
    inputs: list[dict[str, Any]]
    sections: Annotated[list[dict[str, Any]], operator.add]
    output: dict[str, Any]  # trackflow.rfp_drafting.handoff/v1
    outcome: str
