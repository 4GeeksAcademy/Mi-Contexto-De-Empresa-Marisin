"""Runner CLI de la Parte 3 de RFPs: aprobación humana, arbitraje y documento final. No es un segundo API.

Usos:

    # Ruta E2E reproducible (sin BD ni LLM): Partes 1 → 3 con aprobaciones simuladas
    # (resume programático) y checkpointer SQLite en disco. Sale con código 1 si falla
    # alguna comprobación. Escenarios: parallel | returns | volume | limit | all.
    python scripts/rfp_approval_run.py --e2e parallel --out docs/rfp-approval/evidence/e2e-parallel.json

    # Abrir (o reiniciar con --force) la aprobación de un ticket de PostgreSQL:
    python scripts/rfp_approval_run.py --start 2 [--force]

    # Registrar la decisión de un responsable (mismo camino que la UI: validar → resume):
    python scripts/rfp_approval_run.py --decide 2 --department warehouse --decision approve --approver "Ana Whitfield"
    python scripts/rfp_approval_run.py --decide 2 --department lastmile --decision request_changes \\
        --approver "Carlos Vega" --comment "Indica el plazo express en la primera línea."

    # Procesar la cola de la Parte 3 (tickets con ready_for_approval):
    python scripts/rfp_approval_run.py --pending

    # Exportar estado, aprobaciones, documento final y traza de un ticket (evidencia del PR):
    python scripts/rfp_approval_run.py --show 2 --out docs/rfp-approval/evidence/ticket-2-approval.json

El checkpointer es el de la API (`RFP_CHECKPOINTER`, por defecto SQLite en
`data/checkpoints/rfp_approval.sqlite`): la API y el CLI ven los mismos hilos.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402


def sql_store():
    from services.api.database import engine

    if engine is None:
        raise SystemExit("Falta DATABASE_URL en .env (Supabase): --start, --decide, --pending y --show leen PostgreSQL.")
    from data.pipelines.rfp_intake.sql_store import SqlRfpStore

    return SqlRfpStore(engine)


def export(ticket_id: int, store, service) -> dict[str, Any]:
    ticket = store.get_ticket(ticket_id)
    if ticket is None:
        raise SystemExit(f"No existe el ticket {ticket_id}.")
    return {
        "ticket_id": ticket_id,
        "original_filename": ticket.get("original_filename"),
        "status": ticket.get("status"),
        "stage": ticket.get("stage"),
        "error_stage": ticket.get("error_stage"),
        "error_message": ticket.get("error_message"),
        "approval": service.summary(ticket_id),
        "approval_requests": service.pending_requests(ticket_id),
        "sections": [
            {k: s.get(k) for k in ("department_id", "responsible", "draft_status", "iterations", "approval_status",
                                   "approver", "approved_at", "approval_round", "approval_comment",
                                   "approval_requested_at", "approval_history")}
            for s in ticket.get("sections") or []
        ],
        "final_document": store.get_final_document(ticket_id),
        "trace": store.list_trace(ticket_id),
    }


def write(data: Any, out: str | None) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    if out:
        path = Path(out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        print(f"Guardado en {path}")
    else:
        print(text)


def e2e_summary(result: dict[str, Any]) -> str:
    lines = [f"Escenario {result['scenario']} · ticket {result['ticket_id']} ({result['client']}) → "
             f"{result['final_status']} / {result['final_stage']}",
             f"Hilos: {', '.join(result['thread_ids'])}"]
    lines += [f"  {'✓' if c['passed'] else '✗'} {c['check']}" for c in result["checks"]]
    lines.append(f"Trazas: {len(result['trace'])} nodos · documento final: {'sí' if result['final_document'] else 'no'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--e2e", choices=("parallel", "returns", "volume", "limit", "all"), help="ruta E2E sin BD")
    group.add_argument("--start", type=int, metavar="TICKET_ID", help="abre la aprobación de un ticket")
    group.add_argument("--decide", type=int, metavar="TICKET_ID", help="decisión de un responsable")
    group.add_argument("--pending", action="store_true", help="abre la aprobación de los tickets en cola")
    group.add_argument("--show", type=int, metavar="TICKET_ID", help="exporta aprobaciones, documento y traza")
    parser.add_argument("--force", action="store_true", help="con --start: reinicia aunque ya esté esperando aprobación")
    parser.add_argument("--department", choices=("warehouse", "lastmile", "reverse"))
    parser.add_argument("--decision", choices=("approve", "reject", "request_changes"))
    parser.add_argument("--approver", help="responsable del departamento (BRIEFING §2.1)")
    parser.add_argument("--comment", default="")
    parser.add_argument("--out", help="fichero JSON de salida")
    args = parser.parse_args(argv)

    load_dotenv(ROOT / ".env")
    # En --e2e los avisos «sin LLM: plantilla» son esperados: solo se muestran los errores.
    logging.basicConfig(level=logging.ERROR if args.e2e else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    if args.e2e:
        from data.pipelines.rfp_intake.approval.e2e import SCENARIOS, run_scenario

        scenarios = SCENARIOS if args.e2e == "all" else (args.e2e,)
        results = [run_scenario(name) for name in scenarios]
        for result in results:
            print(e2e_summary(result))
        if args.out:
            write(results[0] if len(results) == 1 else results, args.out)
        return 0 if all(r["passed"] for r in results) else 1

    from data.pipelines.rfp_intake.approval.runner import ApprovalService, InvalidDecision
    from data.pipelines.rfp_intake.store import NotApprovable

    store = sql_store()
    service = ApprovalService(store)
    try:
        if args.start is not None:
            write(service.start(args.start, force=args.force), None)
        elif args.decide is not None:
            if not (args.department and args.decision and args.approver):
                parser.error("--decide necesita --department, --decision y --approver")
            payload = {"decision": args.decision, "approver": args.approver, "comment": args.comment}
            write(service.decide(args.decide, args.department, payload), None)
        elif args.pending:
            for ticket in store.list_ready_for_approval():
                try:
                    write(service.start(ticket["ticket_id"]), None)
                except NotApprovable as exc:
                    print(f"Ticket {ticket['ticket_id']} omitido: {exc}")
        else:
            write(export(args.show, store, service), args.out)
    except InvalidDecision as exc:
        print(f"Decisión no válida (no entra al grafo): {exc}", file=sys.stderr)
        return 2
    except NotApprovable as exc:
        print(f"No se puede: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
