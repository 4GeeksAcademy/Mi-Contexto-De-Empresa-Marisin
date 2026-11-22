# `scripts` folder

This folder contains **helper scripts** for the monorepo: development automation, maintenance utilities, repetitive tasks (setup, lint, migrations, data generation, etc.), and internal tooling.

- **Main purpose**: group support tools that do not belong to a specific app, agent, or pipeline but make the team’s work easier.
- **Recommendation**: document each script (what it does, parameters, requirements, usage examples) and keep them reproducible (and safe) across environments.

> _Spanish version: [README.es.md](./README.es.md)._

## `nightly_export.py` — nightly telemetry job (Ticket #DEV-53)

Exports yesterday's (UTC) `telemetry_events` rows to `data/raw/telemetry_YYYY-MM-DD.csv` (only if the file does not exist; backup/audit snapshot), runs the business performance pipeline as a subprocess and records every run in `public.job_runs` (`pending → processing → completed | failed`) through `services/job_runner.py`. The `processing` state is the lock: a second instance aborts silently. Idempotent per `(job_name, target_date)`.

```bash
python scripts/nightly_export.py                         # yesterday (UTC)
TARGET_DATE=2026-11-18 python scripts/nightly_export.py  # a specific day
```

Requires `public.job_runs` (`services/sql/001_job_runs.sql`). Triggered by the OS crontab (`15 1 * * *`, see `infra/cron/`), never inside FastAPI. Plan: `memory-bank/history/2026-11-19_nightly-export.md`.

## `sales_forecast.py` — sales forecasting with Random Forest

Trains a Random Forest on `data/raw/trackflow_sales.csv` using the first 8 years (2016-2023), recursively forecasts the last 2 (2024-2025) without seeing their actuals, and reports MSE, PSI, Gini and K2 Score (R²) on the test set. Writes `docs/sales-forecast/metrics.json`, `test_predictions.csv` and `forecast.png` (forecast with a P10-P90 band).

```bash
python scripts/sales_forecast.py
```

Requires `scikit-learn` and `matplotlib`. Decisions and metrics: `docs/sales-forecast/README.md`. 8/2 split test: `tests/pipelines/test_sales_forecast_split.py`.

## `sales_model_eval.py` — sales model technical evaluation

Time-series cross-validation (`TimeSeriesSplit`, 5 folds, no shuffling, features recomputed per fold to avoid leakage), learning curve, train/validation MAE and RMSE as mean ± std, estimated noise floor and a regularization sweep. Uses 2016-2023 only.

```bash
python scripts/sales_model_eval.py
```

Outputs in `data/eval/` (report: `data/eval/evaluation_report.md`). Test: `tests/pipelines/test_sales_model_eval.py`.

## `rag_eval.py` — RAG retrieval eval

Measures Recall@3 on `data/eval/test-queries.json`, analyses the `min_score` threshold with out-of-scope questions and, with `--answers`, generates the answers and checks their figures against the retrieved context. Run `python -m data.process.rag` first.

```bash
python scripts/rag_eval.py --answers
```

## `agent_record_traces.py` — traces for the LangGraph agent evals

Runs every case in `data/eval/agent-eval-cases.json` through the real graph (Qdrant + the models in `.env` + the TrackFlow API) and stores each trace in `tests/pipelines/fixtures/agent_traces/<id>.json`, which `tests/pipelines/test_agent_evals.py` evaluates. `{ticket_id}` and `{sku}` are replaced with a real ticket and SKU from the API, and the evidence traces are copied to `docs/agent/`. Requires Qdrant running, the collection indexed and the API running (`uvicorn`) with at least one incident and one product.

```bash
python scripts/agent_record_traces.py
```

## `mcp_get_token.py` and `mcp_smoke_test.py` — OAuth-protected MCP server

`mcp_get_token.py` requests an access token (`client_credentials`) from Logto for the MCP server (`--app admin|agent`, `--scopes`, `--claims`); paste it into MCP Playground. `mcp_smoke_test.py` runs every flow as an external client (no token, discovery, incidents, inventory, rejected write, insufficient scope, validation) and saves the output to `docs/mcp/smoke-test.txt`. Both need the API, the MCP server and the `.env` credentials.

```bash
python scripts/mcp_get_token.py
```
```bash
python scripts/mcp_smoke_test.py
```

## `agent_memory_evidence.py` and `agent_memory_consolidate.py` — agent memory

`agent_memory_evidence.py` runs the cases in `data/eval/agent-memory-cases.json` through the agent's real structured call and the memory policy (`self-eval.json`), and runs three full cycles through the real graph: approved and reflected in another conversation, rejected with memory unchanged, and discarded on a topic change. Evidence goes to `docs/agent-memory/evidence/`. Requires the Milestone 7 `.env`, Qdrant with the indexed collection, and Redis. `agent_memory_consolidate.py` runs the cleanup (expired proposals, expired facts, caps) and records it in the audit log; `--show` prints the consolidated memory.

```bash
python scripts/agent_memory_evidence.py
```
```bash
python scripts/agent_memory_consolidate.py --show
```

## `agent_guardrails_evidence.py` and `agent_guardrails_report.py` — agent harness and guardrails

`agent_guardrails_evidence.py` runs the `data/eval/agent-guardrail-cases.json` battery (the 4 BRIEFING cases, jailbreak variants, personal use, sensitive data, small talk and domain questions) through the real graph with a synthetic session user, checks each case's status and category, and writes `docs/agent-guardrails/evidence/harness-cases.json` plus the session summary `guardrails-summary.json`. Requires the Milestone 7 `.env`, Qdrant and Redis. `agent_guardrails_report.py` prints how many times each guardrail fired, by guard, category, failure type and action (`--since` to scope a test session); same as `GET /agent/guardrails/summary`.

```bash
python scripts/agent_guardrails_evidence.py
```
```bash
python scripts/agent_guardrails_report.py
```
