# Carpeta `data/pipelines`

Esta carpeta agrupa **todos los pipelines de datos del monorepo** relacionados con la compañía: procesos de ingesta, ETL/ELT, limpieza, transformación y carga hacia sistemas analíticos o de producción.

Cada subcarpeta o archivo dentro de `data/pipelines/` debe representar **un pipeline o conjunto de jobs** (por ejemplo `sales-etl`, `telemetry-stream`, `customer-segmentation`) e incluir la configuración necesaria (scripts, orquestación, conectores, esquemas, etc.).

- **Propósito principal**: unificar en un único lugar la lógica de movimiento y transformación de datos que soporta las aplicaciones y analíticas de la compañía.
- **Recomendación**: documenta aquí los pipelines que vayas añadiendo, describiendo su objetivo, orígenes/destinos de datos, dependencias y cómo ejecutarlos en desarrollo, pruebas y producción.

## `rag.py` — recuperación y generación del RAG (Hito 7)

`retrieve()` (top-k con umbral `min_score`), `generate_answer()` (prompt con la voz de vendedor de TrackFlow + `LLM_MODEL`) y `query()` = `retrieve()` + `generate_answer()`, que es lo que llama `POST /knowledge/query`. Diseño: `docs/rag/rag-design.md`.
