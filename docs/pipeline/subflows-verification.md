# Verificación de los subflows, los tests y el dashboard (Parte 3 de 3)

Verificación del 19-11-2026 en el Codespace, rama `feature/pipeline-subflows`. Diseño: `data/pipelines/PIPELINE_DESIGN.md` §9.5 (subflows) y §16 (dashboard).

## 1. Tests

| Comando | Resultado |
|---|---|
| `python -m pytest tests/pipelines/test_pipeline.py` | **13 passed**: un test por KPI del BRIEFING, valores calculados a mano (Volumen 20 + 5 = 25 unidades; Tasa 1 / 4 = 0,25), tasa 0 sin pedidos, deduplicación, exclusión de verificación, semana ISO y 4 tests defensivos |
| `python -m pytest -q` | **148 passed** (los 132 de la Parte 2 + 13 unitarios + 3 de subflows ejecutados por separado; el test de caché se renombró a `prepare_kpi_events`) |

Los tests unitarios llaman a la función de cada task (`task.fn`) con DataFrames en memoria con la forma de la extracción de `telemetry_events`, sin base de datos ni Prefect. La primera ejecución destapó que `get_run_logger()` falla fuera de un run; se corrigió con `task_logger()` (commit `fix: usar un logger seguro en los tasks fuera de un run de Prefect`).

## 2. CLI tras el refactor

`python data/pipelines/pipeline.py --week-start 2026-11-16` → `completed`, `run_id 093c790e-e6ba-4a2e-8191-b15feb630289`. El log muestra el flow principal lanzando los subflows `compute_weekly_warehouse_client_kpis` (con `prepare_kpi_events`, `compute_inbound_volume`, `compute_outbound_throughput`, `compute_stockout_frequency`, `compute_discrepancy_rate` y `validate_weekly_kpis`), `check_capture_coverage`, `load_weekly_warehouse_client_performance` y `export_weekly_performance_snapshot`, todos `Completed`. Carga: `rows_unchanged = 1`, el mismo resultado que en la Parte 2.

## 3. Dashboard `/reporting`

Con la API (`uvicorn services.api.main:app --port 8000`) y el backoffice (`npm run dev`), sesión de `admin@test.com` y enlace "Reporte semanal":

- Cabecera "Semana del 16 al 22 de noviembre de 2026", aviso de semana en curso y "Última actualización: 19 nov 2026, 14:42".
- Tarjetas: **Volumen de entrada** 1 unidad, **Throughput de salida** 1 pedido, **Frecuencia de quiebre de stock** 0 veces y **Tasa de discrepancia** 0 % (0 discrepancias / 1 pedidos), los mismos valores que la fila de `reporting.weekly_warehouse_client_performance`.
- Una tabla con barra por KPI: Los Ángeles (EE. UU.) × EcoWear USA.
- "← Semana anterior" → "No hay datos calculados para la semana del 9 al 15 de noviembre de 2026."; "Semana siguiente" desactivado en la semana actual.
- Swagger sigue mostrando los mismos 3 endpoints de `reporting`: el dashboard los consume sin cambios en `services/reporting/`.

## 4. Fuera de alcance comprobado

No cambian `telemetry_events`, `services/telemetry/analysis.py`, `GET /telemetry/report`, `services/reporting/` ni el esquema `reporting`.

## 5. Evidencias

| Evidencia | Fichero |
|---|---|
| `python -m pytest tests/pipelines/test_pipeline.py` → 13 passed | [parte3-pytest-test-pipeline.png](evidence/parte3-pytest-test-pipeline.png) |
| `python -m pytest -q` → 148 passed | [parte3-pytest-suite-completa.png](evidence/parte3-pytest-suite-completa.png) |
| CLI con los subflows en el log | [parte3-cli-subflows.png](evidence/parte3-cli-subflows.png) |
| Dashboard de la semana del 16-11-2026 | [parte3-dashboard-semana.png](evidence/parte3-dashboard-semana.png) |
| Semana sin datos (9-11-2026) | [parte3-dashboard-semana-sin-datos.png](evidence/parte3-dashboard-semana-sin-datos.png) |
| Endpoints de `reporting` en Swagger | [parte3-swagger-reporting.png](evidence/parte3-swagger-reporting.png) |
