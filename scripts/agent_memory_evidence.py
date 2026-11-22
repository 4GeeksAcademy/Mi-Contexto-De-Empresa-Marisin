"""Evidencias de la memoria del agente con el LLM, el RAG y Redis reales (Hito 8 · Parte 1).

1. **Auto-evaluación** (`self-eval.json`): pasa cada caso de
   `data/eval/agent-memory-cases.json` por la llamada estructurada real del agente
   (`routing.classify_with_llm`) y por la política, y comprueba que propone lo
   memorable, nada en lo que no lo es y que lo prohibido nunca llega al usuario.
2. **Ciclo aprobado** (`cycle-approved.json`): propuesta → "sí, recuérdalo" →
   consolidación → la nota aparece en una pregunta de **otra** conversación.
3. **Ciclo rechazado** (`cycle-rejected.json`): propuesta → "no, no hace falta" →
   la memoria queda idéntica y la nota no aparece después.
4. **Ciclo ambiguo** (`cycle-topic-change.json`): propuesta → otra pregunta →
   se descarta sin guardar y la pregunta se responde.

Cada ciclo guarda los turnos (respuesta, ruta del grafo, estado de la memoria),
la memoria antes y después y las entradas de auditoría de su propuesta.

Requiere: `.env` del Hito 7 (LLM y embeddings), Qdrant con la colección indexada
(`docker compose up -d qdrant`) y Redis (`docker compose up -d redis`).

    python scripts/agent_memory_evidence.py
    python scripts/agent_memory_evidence.py --only self-eval
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from services.agent import routing  # noqa: E402
from services.agent.memory import policy  # noqa: E402
from services.agent.memory import store as memory_store  # noqa: E402
from services.agent.runner import run_agent  # noqa: E402

CASES_PATH = ROOT / "data" / "eval" / "agent-memory-cases.json"
EVIDENCE_DIR = ROOT / "docs" / "agent-memory" / "evidence"
# Agente de CX sintético para la evidencia (la API usa el usuario del JWT).
EVIDENCE_USER = {"id": 9001, "role": "user"}

CYCLES = {
    "approved": {
        "turns": [
            "En realidad SEUR ya no cubre esa zona rural de Zaragoza, hay que usar el carrier local desde el mes pasado.",
            "sí, recuérdalo",
        ],
        "later": "¿Qué transportista uso para un envío a la zona rural de Zaragoza?",
        "expected_outcome": "approved",
    },
    "rejected": {
        "turns": [
            "El cliente de cosméticos siempre quiere su reporte mensual con el desglose de devoluciones primero, "
            "antes que el volumen de envíos.",
            "no, no hace falta",
        ],
        "later": "¿Cómo preparo el reporte mensual del cliente de cosméticos?",
        "expected_outcome": "rejected",
    },
    "topic-change": {
        "turns": [
            "Esos retrasos reportados en incidencias de Los Ángeles esta semana son por la huelga portuaria, "
            "no por un problema nuestro — ya van tres tickets sobre lo mismo.",
            "¿Cuál es la ventana de devolución estándar?",
        ],
        "later": None,
        "expected_outcome": "discarded_topic_change",
    },
}


def write(name: str, payload: dict[str, Any]) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# 1. Auto-evaluación
# --------------------------------------------------------------------------- #
def self_eval() -> bool:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    rows, ok = [], True
    for case in cases:
        try:
            decision = routing.classify_with_llm(case["message"])
            error = None
        except Exception as exc:
            decision, error = None, f"{type(exc).__name__}: {str(exc)[:160]}"
        draft = decision.memory_proposal if decision else None
        verdict = policy.check_draft(draft, message=case["message"]) if draft else None
        if draft is None:
            observed = "none"
        else:
            observed = "propose" if verdict.allowed else "blocked"
        # Lo prohibido puede acabar en "none" (el modelo no lo propone) o en "blocked" (la política lo para):
        # en ambos casos nunca llega al usuario.
        passed = observed == case["expected"] or (case["expected"] == "blocked" and observed == "none")
        if case["expected"] == "propose" and passed:
            passed = draft.category.value == case["category"]
        ok &= passed and error is None
        rows.append({
            "id": case["id"], "expected": case["expected"], "observed": observed, "passed": passed,
            "message": policy.redact(case["message"]),
            "memory_proposal": draft.model_dump(mode="json", exclude_none=True) if draft and verdict.allowed else None,
            "policy_reasons": verdict.reasons if verdict else [],
            "route": decision.sources if decision else None, "error": error,
        })
        print(f"{case['id']}: esperado={case['expected']:<8} observado={observed:<8} {'OK' if passed else 'FALLA'}")
    summary = {kind: sum(1 for r in rows if r["expected"] == kind and r["passed"]) for kind in ("propose", "none", "blocked")}
    path = write("self-eval.json", {"passed": ok, "summary": summary, "cases": rows})
    print(f"→ {path.relative_to(ROOT)}  {summary}")
    return ok


# --------------------------------------------------------------------------- #
# 2-4. Ciclos completos
# --------------------------------------------------------------------------- #
def snapshot() -> list[dict[str, Any]]:
    return [slot.model_dump(mode="json") for slot in memory_store.get_store().list_slots()]


def turn(question: str, conversation_id: str | None) -> dict[str, Any]:
    result = run_agent(question, conversation_id=conversation_id, user=EVIDENCE_USER)
    trace = json.loads(result.trace_path.read_text(encoding="utf-8"))
    return {
        "question": question, "run_id": result.run_id, "conversation_id": result.conversation_id,
        "status": result.status, "path": trace["path"], "answer": result.answer, "memory": result.memory,
    }


def cycle(name: str, spec: dict[str, Any]) -> bool:
    before = snapshot()
    first = turn(spec["turns"][0], None)
    proposal = (first["memory"].get("proposal") or {})
    turns = [first]
    if proposal.get("status") != "proposed":
        print(f"[{name}] el modelo no propuso nada en el primer turno ({proposal or 'sin propuesta'}).")
        write(f"cycle-{name}.json", {"passed": False, "turns": turns, "memory_before": before})
        return False
    turns.append(turn(spec["turns"][1], first["conversation_id"]))
    after = snapshot()
    later = turn(spec["later"], None) if spec["later"] else None

    outcome = (turns[1]["memory"].get("decision") or {}).get("outcome")
    audit = [e for e in memory_store.get_store().audit_log(500) if e.get("proposal_id") == proposal["proposal_id"]]
    checks = {"outcome": outcome == spec["expected_outcome"]}
    if name == "approved":
        checks["memory_changed"] = after != before
        checks["used_later"] = bool(later and later["memory"].get("notes"))
    else:
        checks["memory_unchanged"] = after == before
        if later:
            checks["not_used_later"] = proposal["fact"] not in later["answer"]
    passed = all(checks.values())
    path = write(f"cycle-{name}.json", {
        "passed": passed, "checks": checks, "proposal": proposal, "turns": turns,
        "later_interaction": later, "memory_before": before, "memory_after": after, "audit": audit,
    })
    print(f"[{name}] {'OK' if passed else 'FALLA'} {checks} → {path.relative_to(ROOT)}")
    return passed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evidencias de la memoria del agente")
    parser.add_argument("--only", choices=["self-eval", *CYCLES], default=None)
    parser.add_argument("--backend", choices=["redis", "memory"], default=None)
    args = parser.parse_args(argv)
    load_dotenv(ROOT / ".env")
    memory_store.set_store(memory_store.build_store(args.backend))

    results = []
    if args.only in (None, "self-eval"):
        results.append(self_eval())
    for name, spec in CYCLES.items():
        if args.only in (None, name):
            results.append(cycle(name, spec))
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
