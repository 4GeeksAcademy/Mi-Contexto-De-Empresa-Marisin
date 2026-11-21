"""Graba los traces del agente LangGraph que usan los evals (Partes 1 y 2).

Ejecuta cada caso de `data/eval/agent-eval-cases.json` con el grafo real
(Qdrant + modelos de 4Geeks del `.env` + API de TrackFlow) y guarda el trace en
`tests/pipelines/fixtures/agent_traces/<id>.json`. Los evals de
`tests/pipelines/test_agent_evals.py` leen esos ficheros: no vuelven a llamar
al LLM ni a la API cada vez que se ejecutan.

Datos reales, nunca inventados:

* `{ticket_id}` se sustituye por el ticket actualizado más recientemente en
  `GET /api/incidents`, y `{sku}` por el primer producto de
  `GET /inventory/products` que no sea de carga sintética (`LOAD-…`).
* Un caso con `backend_url` apunta las tools a ese URL (un puerto cerrado) para
  grabar el fallback de "servicio caído".

Evidencias para el PR:

* `docs/agent/trace-example.json` — trace del caso a01 (RAG).
* `docs/agent/trace-ticket-tool.json` — trace del caso a07 (tool de tickets).
* `docs/agent/trace-rag-routing.json` — trace del caso a08 (RAG, sin tools).

Requiere: Qdrant arriba con la colección indexada, el `.env` del Hito 7 y la
API en marcha (`uvicorn services.api.main:app --port 8000`) con al menos un
incidente y un producto.

    python scripts/agent_record_traces.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.agent import tools  # noqa: E402
from services.agent.runner import AgentRunError, run_agent  # noqa: E402
from services.agent.tracing import load_trace  # noqa: E402

CASES_PATH = ROOT / "data" / "eval" / "agent-eval-cases.json"
FIXTURES_DIR = ROOT / "tests" / "pipelines" / "fixtures" / "agent_traces"
EVIDENCE = {
    "a01": ROOT / "docs" / "agent" / "trace-example.json",
    "a07": ROOT / "docs" / "agent" / "trace-ticket-tool.json",
    "a08": ROOT / "docs" / "agent" / "trace-rag-routing.json",
}


def real_eval_vars() -> dict[str, str]:
    """Un ticket y un SKU que existen de verdad en la API (lectura con las propias tools)."""
    tickets = tools.lookup_tickets(tools.TicketQuery())
    if tickets.status != "ok":
        raise SystemExit(
            f"No hay tickets que usar ({tickets.status}: {tickets.error}). "
            f"Arranca la API en {tools.backend_url()} y crea al menos un incidente."
        )
    try:
        products = [tools.ProductStock.model_validate(item) for item in tools.http_get_json("/inventory/products")]
    except (tools.ToolUnavailable, tools.ToolNotFound) as exc:
        raise SystemExit(f"No se pudo leer el inventario: {exc}") from exc
    real = [product for product in products if not product.sku.upper().startswith("LOAD-")] or products
    if not real:
        raise SystemExit("El inventario está vacío: crea al menos un producto.")
    return {"ticket_id": tickets.records[0]["id"], "sku": real[0].sku}


def record(case: dict, eval_vars: dict[str, str]) -> tuple[dict, bool]:
    question = case["question"].format(**eval_vars)
    previous_url = os.environ.get(tools.BACKEND_URL_ENV)
    if case.get("backend_url"):
        os.environ[tools.BACKEND_URL_ENV] = case["backend_url"]
    try:
        result = run_agent(question)
        trace, ok = load_trace(result.run_id), True
    except AgentRunError as exc:
        trace, ok = load_trace(exc.run_id), False
        print(f"{case['id']}: ERROR en {exc.failed_node} (run_id {exc.run_id})")
    finally:
        if previous_url is None:
            os.environ.pop(tools.BACKEND_URL_ENV, None)
        else:
            os.environ[tools.BACKEND_URL_ENV] = previous_url
    used = {key: value for key, value in eval_vars.items() if "{" + key + "}" in case["question"]}
    return {"eval_case": case["id"], "eval_vars": used, **trace}, ok


def main() -> int:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    eval_vars = real_eval_vars()
    print(f"Datos reales: ticket {eval_vars['ticket_id']} · SKU {eval_vars['sku']}\n")
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    failures = 0

    for case in cases:
        trace, ok = record(case, eval_vars)
        failures += not ok
        path = FIXTURES_DIR / f"{case['id']}.json"
        path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        decided = (trace.get("route") or {}).get("decided_by", "—")
        sources = " + ".join(trace.get("sources") or []) or "—"
        print(f"{case['id']}: {trace['status']:<13} [{sources}; decide {decided}] {' → '.join(trace['path'])}")
        answer = (trace.get("answer") or "—").splitlines()[0]
        print(f"      {answer}")

    for case_id, target in EVIDENCE.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((FIXTURES_DIR / f"{case_id}.json").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\nTraces en {FIXTURES_DIR.relative_to(ROOT)}; evidencias en docs/agent/")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
