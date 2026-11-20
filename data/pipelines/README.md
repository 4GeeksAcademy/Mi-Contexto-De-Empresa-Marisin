# `data/pipelines` folder

This folder groups **all data pipelines in the monorepo** related to the company: ingestion, ETL/ELT, cleaning, transformation, and loading into analytical or production systems.

Each subfolder or file under `data/pipelines/` should represent **one pipeline or job set** (for example `sales-etl`, `telemetry-stream`, `customer-segmentation`) and include the required configuration (scripts, orchestration, connectors, schemas, etc.).

- **Main purpose**: consolidate in one place the data movement and transformation logic that powers the company’s applications and analytics.
- **Recommendation**: document pipelines as you add them—their goal, data sources and sinks, dependencies, and how to run them in development, testing, and production.

> _Spanish version: [README.es.md](./README.es.md)._

## `rag.py` — RAG retrieval and generation (Milestone 7)

`retrieve()` (top-k with a `min_score` threshold), `generate_answer()` (TrackFlow salesperson prompt + `LLM_MODEL`) and `query()` = `retrieve()` + `generate_answer()`, called by `POST /knowledge/query`. Design: `docs/rag/rag-design.md`.
