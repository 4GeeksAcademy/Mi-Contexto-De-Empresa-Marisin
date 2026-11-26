"""Recorrido reproducible Partes 1 → 3 con aprobaciones humanas simuladas (sin BD ni LLM).

Lo usan `scripts/rfp_approval_run.py --e2e` (evidencia del PR) y
`tests/pipelines/test_rfp_approval_e2e.py`. Cada escenario:

1. Parte 1: el grafo `rfp_intake` real sobre una muestra del BRIEFING (el PDF se
   sustituye por su Markdown ya convertido; nada más se simula).
2. Parte 2: el grafo `rfp_drafting` real (plantillas sin LLM, o un LLM simulado
   que incumple una regla para provocar un conflicto).
3. Parte 3: `ApprovalService` con un checkpointer SQLite en disco; las decisiones
   de los responsables son `resume` programáticos (`decide`). Entre decisiones se
   crea un servicio **nuevo** sobre el mismo fichero: la rama se reanuda desde
   el checkpoint como si la API se hubiera reiniciado.

Escenarios:

- `parallel` (Luna Cosmetics, warehouse + lastmile): Carlos Vega aprueba
  lastmile mientras warehouse sigue interrumpida; Ana Whitfield pide cambios
  (vuelve al generador de la Parte 2) y después aprueba; una decisión con un
  aprobador que no es el responsable se rechaza sin tocar el grafo → documento final.
- `returns` (ModaViva, warehouse + reverse): la sección de reverse llega de la
  Parte 2 prometiendo devoluciones en 24 h → `returns-sla-breach`, Sofía Ramos
  fuerza la reescritura → ambas aprobadas → documento final con el arbitraje.
- `volume` (Luna con 30.000 pedidos/mes): `volume-vs-capacity`, Miguel Torres
  limita lastmile a la capacidad de Los Ángeles → documento final.
- `limit` (ModaViva, el generador sigue prometiendo 24 h): el arbitraje agota
  sus rondas → sección rechazada, sin documento final.
"""

from __future__ import annotations

import contextlib
import tempfile
from pathlib import Path
from typing import Any

from .. import config as intake_config
from .. import convert, runner
from ..drafting import handoff as drafting_contract
from ..drafting import runner as drafting_runner
from ..drafting.generators import GENERATORS, generator_for
from ..store import InMemoryRfpStore
from . import config
from .checkpoint import make_checkpointer
from .runner import ApprovalService, InvalidDecision

FIXTURES = intake_config.ROOT / "tests" / "pipelines" / "fixtures" / "rfp"
SAMPLES = {"formal": FIXTURES / "trackflow-request-1.md", "informal": FIXTURES / "trackflow-request-2.md"}
SCENARIOS = ("parallel", "returns", "volume", "limit")
BREACH_LINE = "- Procesamos las devoluciones en 24 horas desde que llegan al almacén."


def offline_llm(system: str, user: str) -> str:
    raise RuntimeError("E2E sin LLM: plantilla del departamento")


class ReturnsBreachLLM:
    """Simula un generador de reverse que promete devoluciones en 24 h (incumple el BRIEFING §5)."""

    def __init__(self, templates: dict[str, str]) -> None:
        self.templates = templates

    def __call__(self, system: str, user: str) -> str:
        if system.startswith(GENERATORS["reverse"].role_prompt) and "reverse" in self.templates:
            return self.templates["reverse"].rstrip() + "\n" + BREACH_LINE + "\n"
        raise RuntimeError("E2E sin LLM: plantilla del departamento")


@contextlib.contextmanager
def _markdown_instead_of_pdf(markdown: str):
    original = convert.pdf_to_markdown
    convert.pdf_to_markdown = lambda path: markdown
    try:
        yield
    finally:
        convert.pdf_to_markdown = original


def _snapshot(store, ticket_id: int, label: str) -> dict[str, Any]:
    ticket = store.get_ticket(ticket_id) or {}
    return {
        "step": label,
        "status": ticket.get("status"),
        "stage": ticket.get("stage"),
        "sections": {s["department_id"]: {"draft_status": s.get("draft_status"), "approval_status": s.get("approval_status"),
                                          "approver": s.get("approver"), "approval_round": s.get("approval_round")}
                     for s in ticket.get("sections") or []},
    }


class Run:
    def __init__(self, scenario: str, checkpoint_path: Path) -> None:
        self.scenario = scenario
        self.checkpoint_path = checkpoint_path
        self.store = InMemoryRfpStore()
        self.timeline: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.ticket_id: int | None = None
        self._checkpointer = None

    # Un servicio nuevo por paso: mismos checkpoints en disco, objetos de grafo nuevos.
    def service(self, llm=None) -> ApprovalService:
        if self._checkpointer is None:
            self._checkpointer = make_checkpointer("sqlite", self.checkpoint_path)
        return ApprovalService(self.store, llm=llm or offline_llm, checkpointer=self._checkpointer)

    def step(self, label: str) -> None:
        self.timeline.append(_snapshot(self.store, self.ticket_id, label))

    def check(self, name: str, passed: bool, detail: Any = None) -> None:
        self.checks.append({"check": name, "passed": bool(passed), "detail": detail})

    def decide(self, department_id: str, decision: str, approver: str, comment: str = "", llm=None) -> dict[str, Any]:
        payload = {"decision": decision, "approver": approver, "comment": comment}
        self.decisions.append({"department_id": department_id, **payload})
        summary = self.service(llm).decide(self.ticket_id, department_id, payload)
        self.step(f"{department_id}: {decision} ({approver})")
        return summary

    def result(self) -> dict[str, Any]:
        ticket = self.store.get_ticket(self.ticket_id) or {}
        document = self.store.get_final_document(self.ticket_id)
        return {
            "scenario": self.scenario,
            "ticket_id": self.ticket_id,
            "client": (ticket.get("metadata") or {}).get("client_name"),
            "final_status": ticket.get("status"),
            "final_stage": ticket.get("stage"),
            "thread_ids": [config.ticket_thread_id(self.ticket_id)]
            + [config.department_thread_id(self.ticket_id, s["department_id"]) for s in ticket.get("sections") or []],
            "decisions": self.decisions,
            "timeline": self.timeline,
            "sections": [
                {k: s.get(k) for k in ("department_id", "responsible", "draft_status", "iterations", "approval_status",
                                       "approver", "approved_at", "approval_round", "approval_comment", "approval_history")}
                for s in ticket.get("sections") or []
            ],
            "final_document": document,
            "trace": [
                {k: e.get(k) for k in ("id", "graph", "thread_id", "department_id", "node", "agent", "status", "finished_at")}
                for e in self.store.list_trace(self.ticket_id)
            ],
            "checks": self.checks,
            "passed": all(c["passed"] for c in self.checks),
        }


def _part1_and_2(run: Run, sample: str, *, markdown_patch: tuple[str, str] | None = None, breach: bool = False) -> None:
    markdown = SAMPLES[sample].read_text(encoding="utf-8")
    if markdown_patch:
        markdown = markdown.replace(*markdown_patch)
    ticket = run.store.create_ticket(
        rfp_id=f"e2e-{run.scenario}", raw_pdf_path=f"data/raw/rfp/e2e-{run.scenario}.pdf",
        original_filename=SAMPLES[sample].name.replace(".md", ".pdf"), file_sha256="0" * 64,
        file_size_bytes=len(markdown), uploaded_by="e2e",
    )
    run.ticket_id = ticket["ticket_id"]
    with _markdown_instead_of_pdf(markdown):
        part1 = runner.process_ticket(run.ticket_id, run.store, llm=offline_llm)
    run.step("Parte 1: análisis")
    run.check("parte1_analisis_completo", part1.outcome == "analysis_complete", part1.outcome)
    llm = offline_llm
    if breach:
        handoff = run.store.get_ticket(run.ticket_id)["handoff"]
        templates = {c.department_id: generator_for(c.department_id).template(c)
                     for c in drafting_contract.drafting_inputs(handoff)}
        llm = ReturnsBreachLLM(templates)
    part2 = drafting_runner.draft_ticket(run.ticket_id, run.store, llm=llm)
    run.step("Parte 2: borradores evaluados")
    ticket = run.store.get_ticket(run.ticket_id)
    run.check("parte2_ready_for_approval", bool(ticket["ready_for_approval"]), part2.sections)


def scenario_parallel(run: Run) -> None:
    _part1_and_2(run, "informal")
    summary = run.service().start(run.ticket_id)
    run.step("Parte 3: aprobaciones abiertas")
    run.check("dos_ramas_interrumpidas", all(b["waiting"] for b in summary["branches"].values()), summary["branches"])
    run.check("ticket_esperando_aprobacion", summary["status"] == config.STATUS_AWAITING, summary["status"])

    summary = run.decide("lastmile", config.DECISION_APPROVE, "Carlos Vega")
    run.check("aprueba_B_con_A_interrumpida",
              summary["branches"]["lastmile"]["approval_status"] == config.APPROVAL_APPROVED
              and summary["branches"]["warehouse"]["waiting"] and summary["status"] == config.STATUS_AWAITING,
              summary["branches"])
    run.check("sin_documento_con_A_pendiente", run.store.get_final_document(run.ticket_id) is None)

    try:
        run.service().decide(run.ticket_id, "warehouse", {"decision": "approve", "approver": "Carlos Vega"})
        rejected = False
    except InvalidDecision as exc:
        rejected = str(exc)
    run.check("decision_invalida_no_entra_al_grafo",
              bool(rejected) and run.service().branch_waiting(run.ticket_id, "warehouse"), rejected)

    summary = run.decide("warehouse", config.DECISION_CHANGES, "Ana Whitfield",
                         "Añade en la primera línea que el onboarding dura 10 días hábiles.")
    branch = run.service().branch_snapshot(run.ticket_id, "warehouse").values
    run.check("request_changes_vuelve_al_generador_y_reinterrumpe",
              summary["branches"]["warehouse"]["waiting"] and branch.get("round") == 1 and len(branch.get("revisions") or []) == 1,
              {"round": branch.get("round")})

    summary = run.decide("warehouse", config.DECISION_APPROVE, "Ana Whitfield")
    document = run.store.get_final_document(run.ticket_id)
    run.check("documento_final_y_terminado", summary["status"] == config.STATUS_DONE and document is not None,
              summary["status"])


def _approve_all(run: Run) -> dict[str, Any]:
    summary = run.service().summary(run.ticket_id)
    for department_id, branch in summary["branches"].items():
        if branch["waiting"]:
            summary = run.decide(department_id, config.DECISION_APPROVE,
                                 intake_config.DEPARTMENTS[department_id].responsible)
    return summary


def scenario_returns(run: Run) -> None:
    _part1_and_2(run, "formal", breach=True)
    reverse = next(s for s in run.store.get_ticket(run.ticket_id)["sections"] if s["department_id"] == "reverse")
    run.check("parte2_deja_reverse_en_needs_human_review", reverse["draft_status"] == "needs_human_review",
              reverse["draft_status"])
    run.service().start(run.ticket_id)
    run.step("Parte 3: arbitraje inicial + aprobaciones abiertas")
    state = run.service().ticket_snapshot(run.ticket_id).values
    arbitrations = state.get("arbitrations") or []
    run.check("arbitraje_returns_sla_breach_por_sofia_ramos",
              any(a["trigger"] == config.TRIGGER_RETURNS_SLA and a["arbiter"] == config.REVERSE_OWNER
                  and a["action"] == "request_changes" for a in arbitrations), arbitrations)
    branch = run.service().branch_snapshot(run.ticket_id, "reverse").values
    run.check("reverse_reescrita_antes_de_pedir_aprobacion", (branch.get("round") or 0) == 1, branch.get("round"))
    summary = _approve_all(run)
    document = run.store.get_final_document(run.ticket_id)
    run.check("documento_final_con_arbitraje",
              summary["status"] == config.STATUS_DONE and document and len(document["arbitrations"]) >= 1, summary["status"])
    run.check("documento_sin_devoluciones_en_24h", document and "24 horas" not in document["markdown"])


def scenario_volume(run: Run) -> None:
    _part1_and_2(run, "informal", markdown_patch=("5,000 orders a month", "30,000 orders a month"))
    run.service().start(run.ticket_id)
    run.step("Parte 3: arbitraje inicial + aprobaciones abiertas")
    state = run.service().ticket_snapshot(run.ticket_id).values
    arbitrations = state.get("arbitrations") or []
    run.check("arbitraje_volume_vs_capacity_por_miguel_torres",
              any(a["trigger"] == config.TRIGGER_VOLUME_CAPACITY and a["arbiter"] == config.COMMERCIAL_DIRECTOR
                  for a in arbitrations), arbitrations)
    branch = run.service().branch_snapshot(run.ticket_id, "lastmile").values
    capacity = config.WAREHOUSE_MONTHLY_CAPACITY["USD"]
    run.check("lastmile_limitado_a_la_capacidad", (branch.get("context") or {}).get("monthly_volume") == capacity,
              (branch.get("context") or {}).get("monthly_volume"))
    summary = _approve_all(run)
    run.check("documento_final", summary["status"] == config.STATUS_DONE, summary["status"])


def scenario_limit(run: Run) -> None:
    _part1_and_2(run, "formal", breach=True)
    handoff = run.store.get_ticket(run.ticket_id)["handoff"]
    templates = {c.department_id: generator_for(c.department_id).template(c)
                 for c in drafting_contract.drafting_inputs(handoff)}
    stubborn = ReturnsBreachLLM(templates)  # el generador sigue prometiendo 24 h también en la Parte 3
    run.service(stubborn).start(run.ticket_id)
    run.step("Parte 3: arbitraje ronda 1")
    for _ in range(config.MAX_ARBITRATION_ROUNDS + 1):
        summary = run.service(stubborn).summary(run.ticket_id)
        waiting = [d for d, b in summary["branches"].items() if b["waiting"]]
        if not waiting or summary["stage"] == config.STAGE_REJECTED:
            break
        for department_id in waiting:
            run.decide(department_id, config.DECISION_APPROVE, intake_config.DEPARTMENTS[department_id].responsible,
                       llm=stubborn)
    ticket = run.store.get_ticket(run.ticket_id)
    state = run.service().ticket_snapshot(run.ticket_id).values
    rounds = [a["round"] for a in state.get("arbitrations") or []]
    run.check("limite_de_arbitraje_aplicado", max(rounds or [0]) == config.MAX_ARBITRATION_ROUNDS + 1, rounds)
    run.check("seccion_rechazada_sin_documento",
              ticket["stage"] == config.STAGE_REJECTED and run.store.get_final_document(run.ticket_id) is None,
              ticket["stage"])


def run_scenario(scenario: str, checkpoint_path: Path | None = None) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Escenario desconocido: {scenario}")
    with tempfile.TemporaryDirectory() as tmp:
        run = Run(scenario, Path(checkpoint_path or Path(tmp) / "rfp_approval_e2e.sqlite"))
        {"parallel": scenario_parallel, "returns": scenario_returns, "volume": scenario_volume,
         "limit": scenario_limit}[scenario](run)
        return run.result()
