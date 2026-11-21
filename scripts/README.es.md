# Carpeta `scripts`

Esta carpeta contiene **scripts auxiliares** del monorepo: automatizaciones de desarrollo, utilidades de mantenimiento, tareas repetitivas (setup, lint, migraciones, generación de datos, etc.) y tooling interno.

- **Propósito principal**: agrupar herramientas de soporte que no pertenecen a una app/agente/pipeline específico, pero facilitan el trabajo del equipo.
- **Recomendación**: documenta cada script (qué hace, parámetros, requisitos, ejemplos de uso) y procura que sean reproducibles (y seguros) en distintos entornos.

## `nightly_export.py` — job nocturno de telemetría (Ticket #DEV-53)

Exporta las filas de `telemetry_events` de ayer (UTC) a `data/raw/telemetry_AAAA-MM-DD.csv` (solo si el fichero no existe; snapshot de backup y auditoría), lanza el pipeline de desempeño de negocio como subproceso y registra cada ejecución en `public.job_runs` (`pending → processing → completed | failed`) mediante `services/job_runner.py`. El estado `processing` es el lock: una segunda instancia aborta en silencio. Idempotente por `(job_name, target_date)`.

```bash
python scripts/nightly_export.py                         # ayer (UTC)
TARGET_DATE=2026-11-18 python scripts/nightly_export.py  # un día concreto
```

Requiere `public.job_runs` (`services/sql/001_job_runs.sql`). Lo dispara el crontab del sistema (`15 1 * * *`, ver `infra/cron/`), nunca dentro de FastAPI. Plan: `memory-bank/history/2026-11-19_nightly-export.md`.

## `sales_forecast.py` — predicción de ventas con Random Forest

Entrena un Random Forest sobre `data/raw/trackflow_sales.csv` con los primeros 8 años (2016-2023), pronostica de forma recursiva los 2 últimos (2024-2025) sin ver sus reales y calcula MSE, PSI, Gini y K2 Score (R²) sobre la prueba. Genera `docs/sales-forecast/metrics.json`, `test_predictions.csv` y `forecast.png` (predicción con banda P10-P90).

```bash
python scripts/sales_forecast.py
python scripts/sales_forecast.py --output-dir /tmp/sales-forecast   # sin tocar los artefactos versionados
```

Requiere `scikit-learn` y `matplotlib`. Decisiones y métricas: `docs/sales-forecast/README.md`. Test del split 8/2: `tests/pipelines/test_sales_forecast_split.py`.

## `sales_model_eval.py` — evaluación técnica del modelo de ventas

Validación cruzada temporal (`TimeSeriesSplit`, 5 folds, sin barajar y con las features recalculadas en cada fold para que no haya fuga), curva de aprendizaje, MAE/RMSE de entrenamiento y validación con media ± desviación estándar, error irreducible estimado y barrido de regularización. Solo usa 2016-2023; la prueba 2024-2025 no se toca.

```bash
python scripts/sales_model_eval.py
```

Salidas en `data/eval/` (reporte: `data/eval/evaluation_report.md`). Test: `tests/pipelines/test_sales_model_eval.py`.

## `rag_eval.py` — eval de retrieval del RAG

Mide Recall@3 sobre `data/eval/test-queries.json`, analiza el umbral `min_score` con preguntas fuera de alcance y, con `--answers`, genera las respuestas y comprueba que sus cifras están en el contexto. Requiere haber ejecutado antes `python -m data.process.rag`.

```bash
python scripts/rag_eval.py --answers
```

## `agent_record_traces.py` — traces de los evals del agente LangGraph

Ejecuta cada caso de `data/eval/agent-eval-cases.json` con el grafo real (Qdrant + modelos del `.env` + API de TrackFlow) y guarda su trace en `tests/pipelines/fixtures/agent_traces/<id>.json`, que es lo que evalúan `tests/pipelines/test_agent_evals.py`. Sustituye `{ticket_id}` y `{sku}` por un ticket y un SKU reales de la API y copia los traces de evidencia a `docs/agent/`. Requiere Qdrant arriba, la colección indexada y la API en marcha (`uvicorn`) con al menos un incidente y un producto.

```bash
python scripts/agent_record_traces.py
```

## `mcp_get_token.py` y `mcp_smoke_test.py` — servidor MCP con OAuth

`mcp_get_token.py` pide un access token (`client_credentials`) en Logto para el servidor MCP (`--app admin|agent`, `--scopes`, `--claims`); se pega en MCP Playground. `mcp_smoke_test.py` recorre como cliente externo todos los flujos (sin token, discovery, incidencias, inventario, escritura rechazada, scope insuficiente, validación) y guarda la salida en `docs/mcp/smoke-test.txt`. Requieren la API, el servidor MCP y el `.env` con las credenciales.

```bash
python scripts/mcp_get_token.py
```
```bash
python scripts/mcp_smoke_test.py
```
