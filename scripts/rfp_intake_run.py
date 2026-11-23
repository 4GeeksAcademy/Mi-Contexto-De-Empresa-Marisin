"""Runner CLI del flujo de recepción de RFPs (Hito 9 · Parte 1). No es un segundo API.

Tres usos:

    # Smoke run de un PDF local, sin HTTP ni BD (almacén en memoria):
    python scripts/rfp_intake_run.py --pdf ruta/trackflow-request-1.pdf

    # Reprocesar un ticket ya creado desde la UI (PostgreSQL, DATABASE_URL):
    python scripts/rfp_intake_run.py --ticket-id 3

    # Exportar el resultado guardado de un ticket (evidencia del PR), sin reprocesar:
    python scripts/rfp_intake_run.py --show 3 --out docs/rfp-intake/evidence/ticket-3.json

`--offline` ejecuta los agentes sin LLM (deciden las reglas). Sin `--out`, el JSON
se imprime por pantalla. El código del grafo vive en `data/pipelines/rfp_intake/`.
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


def offline_llm(system: str, user: str) -> str:
    raise RuntimeError("modo --offline: sin LLM")


def sql_store():
    from services.api.database import engine

    if engine is None:
        raise SystemExit("Falta DATABASE_URL en .env (Supabase): --ticket-id y --show leen PostgreSQL.")
    from data.pipelines.rfp_intake.sql_store import SqlRfpStore

    return SqlRfpStore(engine)


def compact(ticket: dict[str, Any]) -> dict[str, Any]:
    """Lo que Ventas necesita ver: estado, metadatos y handoff (sin extractos repetidos)."""
    handoff = ticket.get("handoff") or {}
    return {
        "ticket_id": ticket.get("ticket_id"),
        "original_filename": ticket.get("original_filename"),
        "status": ticket.get("status"),
        "stage": ticket.get("stage"),
        "error_stage": ticket.get("error_stage"),
        "error_message": ticket.get("error_message"),
        "classification": ticket.get("classification"),
        "metadata": ticket.get("metadata"),
        "ready_for_drafting": ticket.get("ready_for_drafting"),
        "handoff": handoff or None,
        "run": ticket.get("run"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pdf", type=Path, help="PDF local para un smoke run sin BD")
    group.add_argument("--ticket-id", type=int, help="reprocesa un ticket existente en PostgreSQL")
    group.add_argument("--show", type=int, metavar="TICKET_ID", help="muestra el resultado guardado de un ticket")
    parser.add_argument("--offline", action="store_true", help="sin LLM: deciden las reglas")
    parser.add_argument("--out", type=Path, help="escribe el JSON en este fichero")
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from data.pipelines.rfp_intake import runner

    llm = offline_llm if args.offline else None
    if args.pdf:
        if not args.pdf.is_file():
            print(f"No existe {args.pdf}", file=sys.stderr)
            return 1
        ticket = runner.run_file(args.pdf, llm=llm)
    elif args.ticket_id is not None:
        store = sql_store()
        if store.get_ticket(args.ticket_id) is None:
            print(f"No existe el ticket {args.ticket_id}", file=sys.stderr)
            return 1
        result = runner.process_ticket(args.ticket_id, store, llm=llm)
        ticket = store.get_ticket(args.ticket_id) or {}
        ticket["run"] = {"outcome": result.outcome, "duration_ms": result.duration_ms, "nodes": result.nodes, "error": result.error}
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
    outcome = (ticket.get("run") or {}).get("outcome")
    return 1 if outcome == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
