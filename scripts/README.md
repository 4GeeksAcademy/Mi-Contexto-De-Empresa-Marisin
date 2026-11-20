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

Runs every case in `data/eval/agent-eval-cases.json` through the real graph (Qdrant + the models in `.env`) and stores each trace in `tests/pipelines/fixtures/agent_traces/<id>.json`, which `tests/pipelines/test_agent_evals.py` evaluates. The first trace is copied to `docs/agent/trace-example.json`. Requires Qdrant running and the collection indexed.

```bash
python scripts/agent_record_traces.py
```
