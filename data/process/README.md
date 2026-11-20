# `data/process` folder

This folder contains **processed/intermediate data** and/or artifacts produced by pipelines (for example: clean datasets, features, aggregates, intermediate tables, or transformation outputs).

- **Main purpose**: clearly separate “raw” data from data ready for analysis, modeling, or app consumption.
- **Recommendation**: document which pipeline produces each artifact, its schema, refresh cadence, and how quality is validated (checks, constraints, data tests).

> _Spanish version: [README.es.md](./README.es.md)._

## `rag.py` — RAG indexing (Milestone 7)

`setup()` reads `docs/company-knowledge-base/`, splits the documents into semantic chunks, embeds them with `embed()` (`EMBEDDING_MODEL`) and upserts them into the Qdrant collection `trackflow_knowledge` with deterministic IDs. Run `python -m data.process.rag`. Design: `docs/rag/rag-design.md`.
