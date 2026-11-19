# Verificación del script nocturno de telemetría (Ticket #DEV-53)

Pruebas reales del 19-11-2026 en el Codespace y en Supabase, rama `feature/nightly-export` (creada desde `feature/pipeline-subflows`). Plan y decisiones: [`memory-bank/history/2026-11-19_nightly-export.md`](../../memory-bank/history/2026-11-19_nightly-export.md). Disparador: [`infra/cron/`](../../infra/cron/README.md).

Los logs completos de cada prueba están en [`evidencias/`](./evidencias/). Son copias de `logs/`, que no se versiona. En los extractos de abajo, los `run_id` se acortan con `…`.

## 1. Entorno

- Tabla `public.job_runs` creada con `services/sql/001_job_runs.sql` en el SQL Editor de Supabase. `pg_indexes` devuelve `job_runs_pkey`, `job_runs_job_name_target_date_idx` (idempotencia) y `job_runs_single_processing_idx` (índice único parcial `where status = 'processing'`, el lock).
- `python -m pytest tests/test_job_runner.py tests/test_nightly_export.py -q`: **30 passed**.
- `python -m pytest -q`: **178 passed** (148 anteriores + 30 nuevos).
- Sistema en UTC (`date -u`). `cron` instalado con `apt` (paquete del SO, no del proyecto).

## 2. Pruebas

| # | Prueba | Comando | Resultado | Log |
|---|---|---|---|---|
| 1 | Ejecución normal (ayer UTC) | `python scripts/nightly_export.py` | `pending → processing → completed`, CSV `telemetry_2026-11-18.csv`, pipeline `--trigger scheduled`, código 0 | `01_exito.log` |
| 2 | Idempotencia | el mismo comando, otra vez | `skipped … omisión por duplicado`; sin CSV nuevo (misma hora, 15:38) ni pipeline; sin fila nueva; código 0 | `02_duplicado.log` |
| 3 | `TARGET_DATE` | `TARGET_DATE=2026-11-19 python scripts/nightly_export.py` | `fecha de TARGET_DATE`, CSV con **60 filas** (`wc -l` = 61), pipeline `--week-start 2026-11-16 --trigger backfill`, `completed` | `03_target_date.log` |
| 4 | Lock: dos instancias a la vez | A en segundo plano + B 3 s después, `TARGET_DATE=2026-11-17` | B: `skipped … Otra instancia está en processing (lock tomado)`, código 0, sin fila ni pipeline. A: `completed` | `04_lock_a.log`, `04_lock_b.log` |
| 5 | Fallo | `NIGHTLY_EXPORT_PIPELINE_TIMEOUT_SECONDS=1`, `TARGET_DATE=2026-11-16` | `failed` con `TimeoutExpired: …` en el log `ERROR` y en `error_message`; código 1 | `05_fallo.log` |
| 6 | Reintento de un día `failed` | sin el timeout, `TARGET_DATE=2026-11-16` | `CSV ya existente, no se reescribe`, `completed`, código 0 | `06_reintento.log` |
| 7 | SIGTERM a mitad del pipeline | `kill` 5 s después de arrancar, `TARGET_DATE=2026-11-14` | `failed` con `SystemExit: 143`; ninguna fila en `processing` | `07_sigterm.log` |
| 8 | Disparador cron | línea temporal `* * * * *` con `TARGET_DATE=2026-11-13` | cron lanza el script solo: 16:35 UTC `completed`; 16:36, 16:37, 16:38 y 16:39 `skipped … omisión por duplicado` | `nightly_export.log` |

`git status` sigue limpio tras todas las pruebas: los CSV de `data/raw/` y `logs/` están ignorados.

### Extracto: ejecución correcta (prueba 1)

```
2026-11-19T15:38:10Z | INFO | job=nightly_export | status=starting | target_date=2026-11-18 | run_id=- | Arranque (pid=17616, fecha por defecto: ayer UTC).
2026-11-19T15:38:11Z | INFO | job=nightly_export | status=pending | target_date=2026-11-18 | run_id=1ce02603-… | Ejecución registrada.
2026-11-19T15:38:11Z | INFO | job=nightly_export | status=processing | target_date=2026-11-18 | run_id=1ce02603-… | Inicio del trabajo (lock tomado).
2026-11-19T15:38:11Z | INFO | job=nightly_export | status=processing | target_date=2026-11-18 | run_id=1ce02603-… | CSV exportado: data/raw/telemetry_2026-11-18.csv (0 filas).
2026-11-19T15:38:11Z | INFO | job=nightly_export | status=processing | target_date=2026-11-18 | run_id=1ce02603-… | Lanzando el pipeline: -m data.pipelines.pipeline --trigger scheduled
2026-11-19T15:38:28Z | INFO | job=nightly_export | status=processing | target_date=2026-11-18 | run_id=1ce02603-… | Pipeline terminado: pipeline_run_id=3cea7ee2-… status=completed weeks=2026-10-19,2026-10-26,2026-11-02,2026-11-09 inserted=0 updated=0
2026-11-19T15:38:28Z | INFO | job=nightly_export | status=completed | target_date=2026-11-18 | run_id=1ce02603-… | Fin del trabajo: ejecución completada.
2026-11-19T15:38:28Z | INFO | job=nightly_export | status=finished | target_date=2026-11-18 | run_id=1ce02603-… | Salida con código 0 (resultado: completed).
```

### Extracto: instancia bloqueada por el lock (prueba 4, instancia B)

```
2026-11-19T15:56:23Z | INFO | job=nightly_export | status=starting | target_date=2026-11-17 | run_id=- | Arranque (pid=25855, fecha de TARGET_DATE).
2026-11-19T15:56:23Z | INFO | job=nightly_export | status=skipped | target_date=2026-11-17 | run_id=- | Otra instancia está en processing (lock tomado): esta se cancela sin hacer nada.
2026-11-19T15:56:23Z | INFO | job=nightly_export | status=finished | target_date=2026-11-17 | run_id=- | Salida con código 0 (resultado: skipped_locked).
```

La instancia A (pid 25811) había tomado el lock a las 15:56:21 y terminó en `completed` a las 15:56:40.

### Extracto: ejecución fallida (prueba 5)

```
2026-11-19T16:03:52Z | INFO | job=nightly_export | status=processing | target_date=2026-11-16 | run_id=79598105-… | Lanzando el pipeline: -m data.pipelines.pipeline --week-start 2026-11-16 --trigger backfill
2026-11-19T16:03:53Z | ERROR | job=nightly_export | status=failed | target_date=2026-11-16 | run_id=79598105-… | La ejecución falló: TimeoutExpired: Command '[…, '-m', 'data.pipelines.pipeline', '--week-start', '2026-11-16', '--trigger', 'backfill']' timed out after 1 seconds
Traceback (most recent call last):
  …
subprocess.TimeoutExpired: …
codigo de salida: 1
```

## 3. Estado final de `job_runs`

`select job_name, target_date, status, error_message from job_runs order by created_at;`

| job_name | target_date | status | error_message |
|---|---|---|---|
| nightly_export | 2026-11-18 | completed | NULL |
| nightly_export | 2026-11-17 | completed | NULL |
| nightly_export | 2026-11-16 | failed | `TimeoutExpired: Command '['/workspaces/Mi-Contexto-De-Empresa-Marisin/…` |
| nightly_export | 2026-11-16 | completed | NULL |
| nightly_export | 2026-11-15 | completed | NULL |
| nightly_export | 2026-11-14 | failed | `SystemExit: 143` |
| nightly_export | 2026-11-13 | completed | NULL |

- Ninguna fila en `processing` ni en `pending`.
- Las omisiones (pruebas 2 y 4B y los disparos repetidos de cron) no crean fila: quedan registradas en el log con `status=skipped` (decisión J5 del plan).
- La fila del 2026-11-19 (prueba 3) y su CSV se borraron después de la prueba: ese día aún no había terminado. Así la ejecución de cron de esa noche (01:15 UTC del 20) hace el snapshot del día completo en vez de saltarlo como duplicado.
- `reporting.pipeline_runs` registra por su lado las corridas del pipeline (`scheduled` y `backfill`) con sus propios `pipeline_run_id`. Las dos tablas coexisten sin duplicar responsabilidades: `job_runs` guarda la orquestación (CSV, subproceso, lock e idempotencia) y `pipeline_runs`, las fases del ETL.

## 4. CSV

`head -6 data/raw/telemetry_2026-11-19.csv` (prueba 3, 60 filas + cabecera). Captura en el PR.

```
id,timestamp,service,event_type,level,value,message,tags
a69cb94a-…,2026-11-19T05:53:15.695000+00:00,backoffice,page_viewed,info,,"Backoffice route view, using a route template without query parameters.","{""eventId"": …, ""route"": ""/login"", ""schemaVersion"": ""1.0.0"", …, ""userId"": null}"
19be1ca7-…,2026-11-19T05:53:44.520000+00:00,backoffice,web_vital_recorded,info,0,"Client-side LCP, INP or CLS metric for a route template.","{""eventId"": …, ""metric_name"": ""INP"", ""metric_value"": 0, …, ""userId"": ""1""}"
```

`tags` va en JSON. El CSV es solo backup y auditoría: el pipeline lee `telemetry_events` de la base de datos, no este fichero.

## 5. Disparador instalado

`crontab -l` (última línea):

```
15 1 * * * cd /workspaces/Mi-Contexto-De-Empresa-Marisin && mkdir -p logs && .venv/bin/python scripts/nightly_export.py >> logs/nightly_export.log 2>&1
```

Se ejecuta todos los días a las 01:15 UTC. El Codespace solo lo ejecuta mientras está encendido. En producción, el mismo crontab iría en un contenedor scheduler dedicado (ver `infra/cron/README.md`).
