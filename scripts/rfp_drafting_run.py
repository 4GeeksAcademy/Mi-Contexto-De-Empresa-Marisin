"""Runner CLI de la Parte 2 de RFPs: generación y evaluación de borradores. No es un segundo API.

Usos:

    # Generar (o regenerar con --force) los borradores de un ticket de PostgreSQL:
    python scripts/rfp_drafting_run.py --ticket-id 2 [--force]

    # Procesar la cola (tickets en analisis_completo con ready_for_drafting):
    python scripts/rfp_drafting_run.py --pending

    # Exportar los borradores y EvaluationResult guardados de un ticket (evidencia del PR):
    python scripts/rfp_drafting_run.py --show 2 --out docs/rfp-drafting/evidence/ticket-2-drafts.json

    # Demostración del ciclo, sin BD (almacén en memoria) y sin tocar Supabase:
    #   retry  → la 1.ª versión de la sección incumple el BRIEFING, el juez la devuelve
    #            con feedback y la 2.ª pasa.
    #   review → la sección incumple en todas las iteraciones: agota el límite y queda
    #            en needs_human_review con su último borrador y su EvaluationResult.
    python scripts/rfp_drafting_run.py --demo retry --sample formal --department reverse --out …
    python scripts/rfp_drafting_run.py --demo review --from-ticket 2 --out …

`--offline` ejecuta los generadores sin LLM (plantilla de cada departamento).
`--sample` parte de las muestras del BRIEFING ya convertidas a Markdown
(`tests/pipelines/fixtures/rfp/`) pasando por la Parte 1 sin LLM; `--from-ticket`
toma el handoff guardado de un ticket real (solo lectura).
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

SAMPLES = {
    "formal": ROOT / "tests" / "pipelines" / "fixtures" / "rfp" / "trackflow-request-1.md",
    "informal": ROOT / "tests" / "pipelines" / "fixtures" / "rfp" / "trackflow-request-2.md",
}


def offline_llm(system: str, user: str) -> str:
    raise RuntimeError("modo --offline: sin LLM")


def sql_store():
    from services.api.database import engine

    if engine is None:
        raise SystemExit("Falta DATABASE_URL en .env (Supabase): --ticket-id, --pending, --show y --from-ticket leen PostgreSQL.")
    from data.pipelines.rfp_intake.sql_store import SqlRfpStore

    return SqlRfpStore(engine)


def compact(ticket: dict[str, Any]) -> dict[str, Any]:
    """Estado del ticket y, por departamento, el borrador con su EvaluationResult."""
    drafting = ticket.get("drafting_handoff") or {}
    return {
        "ticket_id": ticket.get("ticket_id"),
        "original_filename": ticket.get("original_filename"),
        "status": ticket.get("status"),
        "stage": ticket.get("stage"),
        "error_stage": ticket.get("error_stage"),
        "error_message": ticket.get("error_message"),
        "ready_for_approval": ticket.get("ready_for_approval"),
        "drafting": {key: drafting.get(key) for key in ("contract", "status", "currency", "needs_human_review", "metrics")}
        if drafting else None,
        "sections": [
            {
                "department_id": s.get("department_id"),
                "responsible": s.get("responsible"),
                "draft_status": s.get("draft_status"),
                "iterations": s.get("iterations"),
                "draft_source": s.get("draft_source"),
                "evaluation_results": s.get("evaluation_results"),
                "evaluation_history": [
                    {k: v for k, v in entry.items() if k != "draft_content"} for entry in s.get("evaluation_history") or []
                ],
                "draft_content": s.get("draft_content"),
            }
            for s in ticket.get("sections") or []
        ],
        "run": ticket.get("run"),
    }


# --------------------------------------------------------------------------- #
# Demostración del ciclo (sin BD)
# --------------------------------------------------------------------------- #
def sample_handoff(name: str) -> dict[str, Any]:
    """Parte 1 sin LLM sobre una muestra del BRIEFING ya convertida a Markdown."""
    from data.pipelines.rfp_intake import metadata, orchestrator, signals, synthesizer, workers
    from data.pipelines.rfp_intake.schemas import Workstream

    markdown = SAMPLES[name].read_text(encoding="utf-8")
    rfp_metadata = metadata.rules_metadata(markdown)
    plan = orchestrator.plan_workstreams(markdown, rfp_metadata, llm=offline_llm)
    sections = [
        workers.run_department_worker(Workstream.model_validate(w), rfp_metadata, llm=offline_llm)
        for w in plan["workstreams"]
    ]
    return synthesizer.synthesize(
        ticket_id=None, rfp_id=f"sample-{name}", metadata=rfp_metadata, sections=sections,
        inactive_departments=plan["inactive_departments"], unassigned_requests=plan["unassigned_requests"],
        excluded_services=signals.detect_services(markdown).excluded, readability=None, llm=offline_llm,
    )


def sabotaged(content: str, currency: str | None) -> str:
    """Una sección que incumple el BRIEFING §5: sin tabla de descuentos, con tarifa de UPS y devoluciones en 24 h."""
    lines: list[str] = []
    skipping = False
    for line in content.splitlines():
        if line.startswith("### "):
            skipping = line.startswith("### Descuentos por volumen")
        if not skipping:
            lines.append(line)
    lines += [
        "",
        f"- Con UPS tenemos una tarifa negociada de 3,10 {currency or 'USD'} por paquete que trasladamos al cliente.",
        "- Procesamos las devoluciones en 24 horas desde que llegan al almacén.",
    ]
    return "\n".join(lines)


class DemoLLM:
    """Envuelve el LLM real (o la plantilla): sabotea la sección elegida en las iteraciones indicadas."""

    def __init__(self, department_id: str, bad_iterations: set[int] | None, base, templates: dict[str, str], currency):
        self.department_id = department_id
        self.bad_iterations = bad_iterations  # None = siempre
        self.base = base
        self.templates = templates
        self.currency = currency
        self.calls = 0

    def __call__(self, system: str, user: str) -> str:
        from data.pipelines.rfp_intake.drafting.generators import GENERATORS

        role = GENERATORS[self.department_id].role_prompt
        if not system.startswith(role):
            if self.base is offline_llm:
                raise RuntimeError("modo --offline: sin LLM")
            return self.base(system, user)
        self.calls += 1
        if self.bad_iterations is None or self.calls in self.bad_iterations:
            return sabotaged(self.templates[self.department_id], self.currency)
        if self.base is offline_llm:
            raise RuntimeError("modo --offline: sin LLM")  # → plantilla del departamento
        return self.base(system, user)


def run_demo(mode: str, handoff: dict[str, Any], department: str | None, base_llm) -> dict[str, Any]:
    from data.pipelines.rfp_intake.drafting import handoff as contract
    from data.pipelines.rfp_intake.drafting import runner as drafting_runner
    from data.pipelines.rfp_intake.drafting.generators import generator_for
    from data.pipelines.rfp_intake.store import InMemoryRfpStore

    store = InMemoryRfpStore()
    ticket = store.create_ticket(
        rfp_id=str(handoff.get("rfp_id") or "demo"), raw_pdf_path="(demo: sin PDF)", original_filename=f"demo-{mode}",
        file_sha256="0" * 64, file_size_bytes=1, uploaded_by="cli-demo",
    )
    ticket_id = ticket["ticket_id"]
    handoff = {**copy.deepcopy(handoff), "ticket_id": ticket_id, "ready_for_drafting": True}
    for entry in handoff["departments"]:
        store.save_section(ticket_id, {
            "department_id": entry["department_id"], "department_name": entry["department_name"],
            "responsible": entry["responsible"], "key_aspects": entry.get("key_aspects") or [],
            "open_questions": entry.get("open_questions") or [], "excerpts": [], "source": "rules", "warnings": [],
        })
    store.complete(ticket_id, handoff)
    inputs = {c.department_id: c for c in contract.drafting_inputs(handoff)}
    target = department or next(iter(inputs))
    if target not in inputs:
        raise SystemExit(f"El departamento {target} no está activo en esta RFP ({', '.join(inputs)}).")
    templates = {d: generator_for(d).template(c) for d, c in inputs.items()}
    llm = DemoLLM(target, {1} if mode == "retry" else None, base_llm, templates, (handoff.get("client") or {}).get("currency"))
    result = drafting_runner.draft_ticket(ticket_id, store, llm=llm)
    final = store.get_ticket(ticket_id) or {}
    final["run"] = {"demo": mode, "department": target, "outcome": result.outcome, "iterations": result.iterations,
                    "duration_ms": result.duration_ms, "error": result.error}
    return final


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ticket-id", type=int, help="genera los borradores de un ticket de PostgreSQL")
    group.add_argument("--pending", action="store_true", help="procesa la cola ready_for_drafting")
    group.add_argument("--show", type=int, metavar="TICKET_ID", help="muestra los borradores guardados de un ticket")
    group.add_argument("--demo", choices=("retry", "review"), help="demostración del ciclo sin BD")
    parser.add_argument("--force", action="store_true", help="con --ticket-id: regenera aunque ya tenga borradores")
    parser.add_argument("--sample", choices=tuple(SAMPLES), help="con --demo: muestra del BRIEFING (sin BD)")
    parser.add_argument("--from-ticket", type=int, help="con --demo: handoff de un ticket real (solo lectura)")
    parser.add_argument("--department", choices=("warehouse", "lastmile", "reverse"), help="con --demo: sección a sabotear")
    parser.add_argument("--offline", action="store_true", help="sin LLM: plantilla de cada departamento")
    parser.add_argument("--out", type=Path, help="escribe el JSON en este fichero")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from data.pipelines.rfp_intake.drafting import runner as drafting_runner
    from data.pipelines.rfp_intake.store import NotDraftable

    llm = offline_llm if args.offline else None
    if args.demo:
        if bool(args.sample) == bool(args.from_ticket):
            parser.error("--demo necesita --sample o --from-ticket (uno de los dos)")
        if args.sample:
            handoff = sample_handoff(args.sample)
        else:
            source = sql_store().get_ticket(args.from_ticket)
            if not source or not source.get("handoff"):
                print(f"El ticket {args.from_ticket} no tiene handoff de la Parte 1", file=sys.stderr)
                return 1
            handoff = source["handoff"]
        from data.pipelines.rfp_intake.llm import complete

        ticket = run_demo(args.demo, handoff, args.department, offline_llm if args.offline else complete)
    elif args.pending:
        store = sql_store()
        results = drafting_runner.draft_pending(store, llm=llm)
        print(json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2))
        return 1 if any(r.outcome == "error" for r in results) else 0
    elif args.ticket_id is not None:
        store = sql_store()
        if store.get_ticket(args.ticket_id) is None:
            print(f"No existe el ticket {args.ticket_id}", file=sys.stderr)
            return 1
        try:
            result = drafting_runner.draft_ticket(args.ticket_id, store, llm=llm, force=args.force)
        except NotDraftable as exc:
            print(f"No se pueden generar los borradores: {exc}. (¿Falta --force?)", file=sys.stderr)
            return 1
        ticket = store.get_ticket(args.ticket_id) or {}
        ticket["run"] = {"outcome": result.outcome, "iterations": result.iterations,
                         "duration_ms": result.duration_ms, "error": result.error}
    else:
        ticket = sql_store().get_ticket(args.show)
        if ticket is None:
            print(f"No existe el ticket {args.show}", file=sys.stderr)
            return 1

    output = json.dumps(compact(ticket), ensure_ascii=False, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output + "\n", encoding="utf-8")
        print(f"Guardado en {args.out}")
    else:
        print(output)
    return 1 if (ticket.get("run") or {}).get("outcome") == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
