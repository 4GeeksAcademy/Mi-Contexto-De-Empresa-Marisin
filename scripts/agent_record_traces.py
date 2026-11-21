"""Graba los traces del agente LangGraph que usan los evals.

Ejecuta cada caso de `data/eval/agent-eval-cases.json` con el grafo real
(Qdrant + modelos de 4Geeks del `.env`), guarda el trace de la corrida y lo
copia a `tests/pipelines/fixtures/agent_traces/<id>.json`. Los evals de
`tests/pipelines/test_agent_evals.py` leen esos ficheros: no vuelven a llamar
al LLM cada vez que se ejecutan.

También copia el trace del primer caso a `docs/agent/trace-example.json`
(evidencia para el PR).

Requiere Qdrant arriba, la colección indexada (`python -m data.process.rag`) y
el `.env` del Hito 7 (lo lee `data/process/rag.py`).

    python scripts/agent_record_traces.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.agent.runner import AgentRunError, run_agent  # noqa: E402
from services.agent.tracing import load_trace  # noqa: E402

CASES_PATH = ROOT / "data" / "eval" / "agent-eval-cases.json"
FIXTURES_DIR = ROOT / "tests" / "pipelines" / "fixtures" / "agent_traces"
EXAMPLE_PATH = ROOT / "docs" / "agent" / "trace-example.json"


def main() -> int:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0

    for case in cases:
        try:
            result = run_agent(case["question"])
            trace = load_trace(result.run_id)
        except AgentRunError as exc:
            failures += 1
            trace = load_trace(exc.run_id)
            print(f"{case['id']}: ERROR en {exc.failed_node} (run_id {exc.run_id})")
        trace = {"eval_case": case["id"], **trace}
        path = FIXTURES_DIR / f"{case['id']}.json"
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{case['id']}: {trace['status']:<10} {' → '.join(trace['path'])}")
        answer = (trace.get("answer") or "—").splitlines()[0]
        print(f"      {answer}")

    EXAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXAMPLE_PATH.write_text((FIXTURES_DIR / f"{cases[0]['id']}.json").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\nTraces en {FIXTURES_DIR.relative_to(ROOT)}; ejemplo en {EXAMPLE_PATH.relative_to(ROOT)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
