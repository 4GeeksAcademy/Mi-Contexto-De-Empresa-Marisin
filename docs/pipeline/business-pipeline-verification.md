# Verificación del Pipeline de Desempeño de Negocio (Parte 2 de 3)

Verificación con datos reales del 19-11-2026 en el Codespace y en Supabase, rama `feature/pipeline-implementation`. Diseño y comandos: `data/pipelines/PIPELINE_DESIGN.md` (§15).

## 1. Entorno

- Prefect **3.9.3** (`uv add "prefect>=3"`), servidor temporal local (sin `PREFECT_API_URL`).
- Tablas creadas con `data/pipelines/sql/001_reporting_schema.sql` en el SQL Editor de Supabase. La consulta a `information_schema.tables` devolvió `pipeline_runs` y `weekly_warehouse_client_performance` en el esquema `reporting`.
- `python -m pytest -q`: **132 passed** (100 anteriores + 13 de la transformación, 13 de los endpoints y 6 del flow).

## 2. Corridas

| # | Origen | Comando o petición | Semanas | Resultado | Carga | Transformación |
|---|---|---|---|---|---|---|
| 1 | CLI | `python data/pipelines/pipeline.py --week-start 2026-11-16` | 2026-11-16 | `completed`, `run_id 2e66e0c7-a378-4a7e-83f8-6ff06813b785`, 1437 ms | `rows_inserted = 1` | `Completed` |
| 2 | CLI | el mismo comando, otra vez | 2026-11-16 | `completed`, `run_id 015bab76-26e1-4479-8c4c-46721f8993f4`, 1163 ms | `rows_unchanged = 1` (0 insertadas, 0 actualizadas) | **`Cached`** |
| 3 | CLI | `python data/pipelines/pipeline.py` (por defecto) | 2026-10-19 … 2026-11-09 | `completed`, `run_id f048b0f9-cdad-4c0c-b74c-77277853e1ad`, 1166 ms | 0 filas | `Completed` |
| 4 | API | `POST /reporting/pipeline-runs` `{"week_start": "2026-11-16"}` | 2026-11-16 | `202 pending` → `completed`, `run_id 3d5ad2f7-7bab-4c00-a26c-27c90a7bd648`, 1496 ms, `triggered_by = "1"` | `rows_unchanged = 1` | **`Cached`** |

En las cuatro corridas, las 9 tasks terminaron en `Completed` (o `Cached`) y el flow en `Completed`.

## 3. KPIs frente a la fuente

Eventos `inbound_order_created` en `public.telemetry_events`:

| `client_id` | `userId` | `quantity` | `timestamp` (UTC) | Tratamiento |
|---|---|---|---|---|
| `ecowear_usa` | `1` | 1 | 2026-11-19 05:56:53 | Cuenta |
| `nova_beauty` | `curl_verification` | 12 | 2026-11-19 07:00:01 | Excluido (D7) |

La extracción de la semana devolvió 3 eventos de negocio (de 46 en total): estos dos y un `outbound_order_created` de `ecowear_usa` en `los_angeles`. `events_excluded = 1`, `duplicates_dropped = 0` y `events_rejected = 0`.

Fila resultante en `reporting.weekly_warehouse_client_performance` (una sola tras las cuatro corridas):

| `warehouse` | `client_id` | `week_start` | `inbound_units_count` | `outbound_orders_count` | `stockout_events_count` | `discrepancy_events_count` | `discrepancy_rate` | `computed_at` |
|---|---|---|---|---|---|---|---|---|
| `los_angeles` | `ecowear_usa` | 2026-11-16 | 1 | 1 | 0 | 0 | 0.0 | 2026-11-19 11:44:26.731931+00 |

- **Volumen de entrada** = suma de `quantity` (1), no conteo de órdenes; las 12 unidades de verificación no entran.
- **Tasa de discrepancia** = 0 / 1 pedido de salida = 0.
- **Idempotencia:** `computed_at` es el de la corrida 1. Las corridas 2 y 4 no reescribieron la fila porque sus valores no cambiaron (`is distinct from`).

## 4. Endpoints de `services/reporting/`

Con la API en `python -m uvicorn services.api.main:app --reload --port 8000` y token de `POST /auth/login`:

- `GET /reporting/weekly-warehouse-client-performance` → **200**, contrato del BRIEFING:

```json
{
  "week_start": "2026-11-16",
  "entries": [
    {
      "warehouse": "los_angeles",
      "client_id": "ecowear_usa",
      "inbound_units_count": 1,
      "outbound_orders_count": 1,
      "stockout_events_count": 0,
      "discrepancy_events_count": 0,
      "discrepancy_rate": 0.0
    }
  ]
}
```

- `GET /reporting/pipeline-runs/latest` → **200**. Antes del POST devolvió la corrida 3 y después la 4, con `status`, `started_at`, `finished_at`, `duration_ms`, `records_processed`, `events_by_type`, `rows_*`, `capture_coverage`, `warnings`, `error_type` y `error_message`.
- `POST /reporting/pipeline-runs` → **202** `{"run_id": "3d5ad2f7-7bab-4c00-a26c-27c90a7bd648", "status": "pending", "week_start": "2026-11-16"}`. El log de la API mostró el flow completo en segundo plano (servidor temporal de Prefect, 9 tasks y `Finished in state Completed()`).

## 5. Observabilidad

- **Cobertura de captura** (corridas 1, 2 y 4): en `los_angeles` hubo 6 órdenes de entrada y 4 de salida en `stock_entries`/`stock_exits`, pero solo 1 evento de cada tipo (cobertura 0,17 y 0,25) → avisos `low_capture_coverage`. Son órdenes de la semana creadas antes de instrumentar la captura o en pruebas: es exactamente la pérdida que esta señal debe hacer visible.
- **Silencio** (corrida 3): las semanas cerradas tienen órdenes en el dominio pero ningún evento, ni siquiera técnicos → `capture_silence:no_technical_events` y `capture_silence:<almacén>:<tipo>`. El pipeline no confunde la ausencia de telemetría con actividad cero.
- **Aviso corregido durante la verificación:** Prefect 3.9 avisaba de que `timeout_seconds` no puede interrumpir consultas bloqueantes en tasks síncronas; se quitó (commit `fix: quitar timeout_seconds de las tasks síncronas de Prefect`). La conexión sigue acotada con `connect_timeout=10`.

## 6. Fuera de alcance comprobado

`git diff --stat feature/pipeline-design -- services/telemetry services/api/routes/telemetry.py services/api/sql` está vacío: ni `analysis.py`, ni `GET /telemetry/report`, ni la tabla `telemetry_events` cambian. El pipeline solo ejecuta `select` sobre `telemetry_events`.

## 7. Evidencias

Capturas del Codespace y de Supabase del 19-11-2026. En `api-kpis.png` se recortaron el login, la contraseña de pruebas y el token.

| Evidencia | Fichero |
|---|---|
| Corrida 1 por CLI (`rows_inserted = 1`) | [cli-primera-corrida.png](evidence/cli-primera-corrida.png) |
| Corrida 2: transformación `Cached` y `rows_unchanged = 1` | [cli-segunda-corrida-cached.png](evidence/cli-segunda-corrida-cached.png) |
| Corrida 3 por defecto sobre las 4 semanas cerradas | [cli-corrida-por-defecto.png](evidence/cli-corrida-por-defecto.png) |
| Fuente: `inbound_order_created` en `telemetry_events` | [supabase-fuente-inbound.png](evidence/supabase-fuente-inbound.png) |
| Tabla de destino con una sola fila | [supabase-kpis-una-fila.png](evidence/supabase-kpis-una-fila.png) |
| Log de ejecución en `reporting.pipeline_runs` (corridas 1 y 2) | [supabase-pipeline-runs.png](evidence/supabase-pipeline-runs.png) |
| `GET /reporting/weekly-warehouse-client-performance` | [api-kpis.png](evidence/api-kpis.png) |
| `POST /reporting/pipeline-runs` → 202 | [api-post-respuesta.png](evidence/api-post-respuesta.png) |
| Flow de la corrida 4 en el log de la API | [api-post-y-log.png](evidence/api-post-y-log.png) |
| `GET /reporting/pipeline-runs/latest` tras el disparo manual | [api-ultima-corrida-manual.png](evidence/api-ultima-corrida-manual.png) |
