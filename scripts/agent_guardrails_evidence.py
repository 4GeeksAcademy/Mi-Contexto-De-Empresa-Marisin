"""Evidencia del harness con el grafo real: LLM, Qdrant y Redis (Hito 8 · Parte 2).

Ejecuta la batería `data/eval/agent-guardrail-cases.json` (los 4 casos del
BRIEFING, 7 variantes de jailbreak, uso personal, datos sensibles, small talk y
consultas de dominio) con un usuario de sesión sintético y comprueba, caso a
caso, el estado y la categoría del guardrail. Guarda:

* `docs/agent-guardrails/evidence/harness-cases.json` — cada caso: respuesta,
  ruta del grafo, veredicto del harness y eventos registrados.
* `docs/agent-guardrails/evidence/guardrails-summary.json` — resumen de las
  activaciones de esta sesión de pruebas (el mismo de `GET /agent/guardrails/summary`).

Es un smoke check con modelo vivo, **complementario**: los tests deterministas
(`tests/pipelines/test_agent_guardrails_*.py`) son el criterio de aceptación.

    python scripts/agent_guardrails_evidence.py
    python scripts/agent_guardrails_evidence.py --only J1 A1 P1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from services.agent.harness import events as guard_events  # noqa: E402
from services.agent.memory import store as memory_store  # noqa: E402
from services.agent.runner import AgentRunError, run_agent  # noqa: E402

CASES_PATH = ROOT / "data" / "eval" / "agent-guardrail-cases.json"
EVIDENCE_DIR = ROOT / "docs" / "agent-guardrails" / "evidence"


def run_case(case: dict, user: dict) -> dict:
    try:
        result = run_agent(case["message"], user=user)
    except AgentRunError as exc:
        return {**case, "passed": False, "error": f"{exc.failed_node}: {exc}"}
    trace = json.loads(result.trace_path.read_text(encoding="utf-8"))
    category = (result.guardrail or {}).get("category", "domain")
    status_ok = case["expected_status"] == "any" or result.status == case["expected_status"]
    passed = status_ok and category == case["expected_category"]
    return {
        "id": case["id"], "group": case["group"], "briefing_case": case.get("briefing_case"),
        "message": case["message"], "passed": passed,
        "expected": {"status": case["expected_status"], "category": case["expected_category"]},
        "observed": {"status": result.status, "category": category},
        "guardrail": result.guardrail, "path": trace["path"], "answer": result.answer,
        "guardrail_events": trace.get("guardrail_events", []), "run_id": result.run_id,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidencia del harness del agente con el grafo real")
    parser.add_argument("--only", nargs="*", help="ids de casos (p. ej. J1 A1 P1)")
    parser.add_argument("--backend", choices=["redis", "memory"], default=None)
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    memory_store.set_store(memory_store.build_store(args.backend))
    guard_events.set_log(guard_events.build_log(args.backend))

    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = [c for c in payload["cases"] if not args.only or c["id"] in args.only]
    started = guard_events.utc_now().isoformat(timespec="seconds")

    rows = []
    for case in cases:
        row = run_case(case, payload["session_user"])
        rows.append(row)
        observed = row.get("observed", {})
        print(f"{row['id']:<3} {row['group']:<18} {observed.get('status', 'error'):<10} "
              f"{observed.get('category', '-'):<18} {'OK' if row['passed'] else 'FALLA'}")

    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    passed = all(row["passed"] for row in rows)
    (EVIDENCE_DIR / "harness-cases.json").write_text(
        json.dumps({"passed": passed, "started_at": started, "cases": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = guard_events.get_log().summary(since=started)
    (EVIDENCE_DIR / "guardrails-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n{sum(r['passed'] for r in rows)}/{len(rows)} casos OK")
    print(f"Resumen de la sesión: {summary['total']} activaciones · por tipo de fallo {summary['by_failure_type']}"
          f" · por acción {summary['by_action']}")
    print(f"→ {(EVIDENCE_DIR / 'harness-cases.json').relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
