"""Nodos de los grafos de la Parte 2. Funciones de estado → actualización.

Ciclo de un departamento (`rfp_section_loop`):

- `generate`: el agente generador de **ese** departamento escribe la iteración
  `n` (con el borrador anterior y el feedback si `n > 1`).
- `evaluator_sends`: tres `Send`, uno por evaluador, cada uno con su payload
  mínimo (pregunta de diseño 1): el de legibilidad solo ve el texto.
- `evaluate_readability` / `evaluate_relevance` / `evaluate_compliance`:
  devuelven solo su clave de `checks`.
- `judge`: une los tres en un `EvaluationResult` con `feedback_for_generator`.
- `route_after_judge`: pasa → `finalize`; falla y quedan iteraciones →
  `generate`; agotado el límite → `finalize` como `needs_human_review`.
- `finalize`: arma la `DraftedSection` (último borrador + su evaluación + historial).

Grafo del ticket (`rfp_drafting`): `load_handoff` → `Send` por departamento a
`draft_department` (que ejecuta el ciclo) → `assemble` (handoff a la Parte 3).
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Send

from ..llm import LLM
from . import config, evaluators, handoff as handoff_contract
from .generators import generator_for
from .reporter import NullReporter, Reporter
from .schemas import ComplianceCheck, DraftedSection, DraftingInput, ReadabilityCheck, RelevanceCheck
from .state import DraftingState, SectionState

NODE_GENERATE = "generate"
NODE_READABILITY = "evaluate_readability"
NODE_RELEVANCE = "evaluate_relevance"
NODE_COMPLIANCE = "evaluate_compliance"
NODE_JUDGE = "judge"
NODE_FINALIZE = "finalize"
EVALUATOR_NODES = (NODE_READABILITY, NODE_RELEVANCE, NODE_COMPLIANCE)

NODE_LOAD = "load_handoff"
NODE_DEPARTMENT = "draft_department"
NODE_ASSEMBLE = "assemble"


def _reporter(reporter: Reporter | None) -> Reporter:
    return reporter if reporter is not None else NullReporter()


# --------------------------------------------------------------------------- #
# Ciclo generador-evaluador de un departamento
# --------------------------------------------------------------------------- #
def generate(state: SectionState, llm: LLM | None = None, reporter: Reporter | None = None) -> dict[str, Any]:
    department_id = state["department_id"]
    iteration = int(state.get("iteration") or 0) + 1
    previous = (state.get("draft") or {}).get("content")
    feedback = (state.get("evaluation") or {}).get("feedback_for_generator") if previous else None
    _reporter(reporter).generating(department_id, iteration)
    draft = generator_for(department_id).generate(
        DraftingInput.model_validate(state["context"]),
        iteration=iteration,
        previous=previous,
        feedback=feedback,
        llm=llm,
    )
    draft_dict = draft.model_dump(mode="json")
    _reporter(reporter).drafted(department_id, draft_dict)
    return {"iteration": iteration, "draft": draft_dict}


def evaluator_sends(state: SectionState) -> list[Send]:
    """Los tres evaluadores en paralelo, cada uno con lo mínimo que necesita."""
    context = state["context"]
    base = {"department_id": state["department_id"], "iteration": state["iteration"], "content": state["draft"]["content"]}
    return [
        Send(NODE_READABILITY, dict(base)),
        Send(
            NODE_RELEVANCE,
            {
                **base,
                "client_name": context.get("client_name"),
                "key_aspects": context.get("key_aspects") or [],
                "open_questions": context.get("open_questions") or [],
            },
        ),
        Send(NODE_COMPLIANCE, {**base, "currency": context.get("currency"), "sources": state.get("sources") or []}),
    ]


def evaluate_readability(payload: dict[str, Any], llm: LLM | None = None, reporter: Reporter | None = None) -> dict[str, Any]:
    check = evaluators.evaluate_readability(payload["content"])
    return {"checks": {"readability": {**check.model_dump(mode="json"), "iteration": payload["iteration"]}}}


def evaluate_relevance(payload: dict[str, Any], llm: LLM | None = None, reporter: Reporter | None = None) -> dict[str, Any]:
    check = evaluators.evaluate_relevance(
        payload["content"],
        department_id=payload["department_id"],
        client_name=payload.get("client_name"),
        key_aspects=payload.get("key_aspects") or [],
        open_questions=payload.get("open_questions") or [],
    )
    return {"checks": {"relevance": {**check.model_dump(mode="json"), "iteration": payload["iteration"]}}}


def evaluate_compliance(payload: dict[str, Any], llm: LLM | None = None, reporter: Reporter | None = None) -> dict[str, Any]:
    check = evaluators.evaluate_compliance(
        payload["content"], currency=payload.get("currency"), sources=payload.get("sources") or []
    )
    return {"checks": {"compliance": {**check.model_dump(mode="json"), "iteration": payload["iteration"]}}}


def _check(checks: dict[str, Any], name: str, iteration: int, model):
    data = dict(checks.get(name) or {})
    if data.pop("iteration", None) != iteration:
        raise RuntimeError(f"El evaluador {name} no devolvió resultado para la iteración {iteration}")
    return model.model_validate(data)


def judge(state: SectionState, llm: LLM | None = None, reporter: Reporter | None = None) -> dict[str, Any]:
    iteration = state["iteration"]
    checks = state.get("checks") or {}
    context = state["context"]
    result = evaluators.judge(
        ticket_id=state.get("ticket_id"),
        department_id=state["department_id"],
        iteration=iteration,
        currency=context.get("currency"),
        readability=_check(checks, "readability", iteration, ReadabilityCheck),
        relevance=_check(checks, "relevance", iteration, RelevanceCheck),
        compliance=_check(checks, "compliance", iteration, ComplianceCheck),
    )
    evaluation = evaluators.evaluation_dict(result)
    entry = {
        "iteration": iteration,
        "draft_source": state["draft"]["source"],
        "overall_pass": result.overall_pass,
        "readability_pass": result.readability.passed,
        "relevance_pass": result.relevance.passed,
        "compliance_pass": result.compliance.passed,
        "violations": [v.rule_id for v in result.compliance.violations],
        "missing_aspects": list(result.relevance.missing_aspects),
        "feedback_for_generator": result.feedback_for_generator,
        "draft_content": state["draft"]["content"],
    }
    _reporter(reporter).evaluated(state["department_id"], evaluation, entry)
    return {"evaluation": evaluation, "history": [entry]}


def route_after_judge(state: SectionState) -> str:
    if state["evaluation"]["overall_pass"]:
        return NODE_FINALIZE
    limit = int(state.get("max_iterations") or config.MAX_ITERATIONS)
    return NODE_GENERATE if state["iteration"] < limit else NODE_FINALIZE


def finalize(state: SectionState, llm: LLM | None = None, reporter: Reporter | None = None) -> dict[str, Any]:
    context = state["context"]
    passed = bool(state["evaluation"]["overall_pass"])
    section = DraftedSection(
        department_id=state["department_id"],
        department_name=context["department_name"],
        responsible=context["responsible"],
        draft_status=config.SECTION_PASSED if passed else config.SECTION_NEEDS_REVIEW,
        provisional=not passed,
        iterations=state["iteration"],
        draft_content=state["draft"]["content"],
        draft_source=state["draft"]["source"],
        evaluation_result=state["evaluation"],
        evaluation_history=list(state.get("history") or []),
    ).model_dump(mode="json")
    _reporter(reporter).finished(state["department_id"], section)
    return {"final": section}


# --------------------------------------------------------------------------- #
# Grafo del ticket
# --------------------------------------------------------------------------- #
def load_handoff(state: DraftingState, llm: LLM | None = None, reporter: Reporter | None = None) -> dict[str, Any]:
    handoff = handoff_contract.validate_input(state.get("handoff"))
    inputs = handoff_contract.drafting_inputs(handoff)
    return {"inputs": [context.model_dump(mode="json") for context in inputs]}


def department_sends(state: DraftingState) -> list[Send]:
    sends = []
    for context in state.get("inputs") or []:
        model = DraftingInput.model_validate(context)
        sends.append(
            Send(
                NODE_DEPARTMENT,
                {
                    "ticket_id": state.get("ticket_id"),
                    "department_id": model.department_id,
                    "context": context,
                    "sources": handoff_contract.anchor_sources(model),
                    "max_iterations": config.MAX_ITERATIONS,
                },
            )
        )
    return sends


def assemble(state: DraftingState, llm: LLM | None = None, reporter: Reporter | None = None) -> dict[str, Any]:
    output = handoff_contract.output_handoff(
        ticket_id=state.get("ticket_id"), input_handoff=state["handoff"], sections=state.get("sections") or []
    )
    return {"output": output, "outcome": "drafts_ready"}
