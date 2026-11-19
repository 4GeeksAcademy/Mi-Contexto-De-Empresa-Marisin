# Plan por fases — Procesos en Segundo Plano: script nocturno de telemetría (TrackFlow)

> **Proyecto 4Geeks:** "Procesos en Segundo Plano" — Ticket #DEV-53, *Script nocturno de telemetría*.
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Ubicación de este plan:** `memory-bank/history/2026-11-19_nightly-export.md`. Prompt en `prompts/nightly-export/prompt.md`.
> **Rama:** `feature/nightly-export`, creada por Marisin **desde `feature/pipeline-subflows`** (PR #19–#23 pendientes; el script lanza el pipeline del Hito 6, que solo existe en esa cadena). Cadena: `main ← #19 ← #20 ← #21 ← #22 ← #23 ← esta`.
> **Ejecución:** Claude implementa y entrega un parche (`git am`); Marisin ejecuta el SQL en Supabase, pytest, el script, las pruebas de lock/fallo, el crontab y el push.
> **Etiqueta del PR:** `cronjob`.

---

## 0. Reglas

1. Un commit por acción, prefijo convencional y descripción en español.
2. Git solo en local para quien implementa; Marisin crea la rama, aplica los parches y hace push.
3. Nada de `git add .` / `-A` / `git add data/`; el JSON local de TinyDB de proveedores nunca se nombra ni se commitea; ningún `.env*` se lee ni se edita.
4. No se tocan `telemetry_events`, `reporting.pipeline_runs`, `data/pipelines/` ni `services/api/`. El script **no importa FastAPI** ni nada de `services/api/` (`database.py` abre TinyDB al importarse).
5. Sin dependencias nuevas de Python ni manifiestos/lockfiles. `cron` es un paquete del sistema operativo del Codespace (`apt`), no del proyecto.
6. Los CSV generados y los logs no se versionan; las evidencias van en `docs/nightly-export/`.

---

## 1. Rúbrica (resumen)

- Proceso independiente de la API (ni en el hilo de FastAPI ni con `APScheduler`, `@repeat_every` o lifespan).
- Máquina de estados `pending → processing → completed | failed` en `job_runs`, con `target_date`, timestamps y `error_message`.
- El estado `processing` **es** el lock distribuido (sin tabla/columna/flag aparte); dos instancias a la vez → la segunda aborta en silencio.
- Idempotencia por `(job_name, target_date)`: dos ejecuciones del mismo día = una (sin duplicar CSV ni pipeline).
- Ningún registro queda en `processing` tras un fallo (`try/except/finally`).
- CSV `data/raw/telemetry_AAAA-MM-DD.csv` desde `telemetry_events`, solo si no existe; es backup, el pipeline lee de BD.
- `job_runs` y `pipeline_runs` coexisten sin duplicar responsabilidades.
- Logs `INFO`/`ERROR` con timestamp, nombre del job y estado.
- Disparador en crontab o scheduler, expresión documentada en el PR. `TARGET_DATE` opcional.
- PR: cron + justificación, log de éxito y de fallo/bloqueo, primeras filas del CSV, etiqueta `cronjob`.

## 2. Decisiones (J1–J10)

| # | Decisión | Por qué |
|---|---|---|
| J1 | Tabla nueva `public.job_runs` (`services/sql/001_job_runs.sql`), separada de `reporting.pipeline_runs`. | Capas distintas: `job_runs` = orquestación nocturna (CSV, subproceso, lock, idempotencia); `pipeline_runs` = fases internas del ETL. |
| J2 | Campos `id, job_name, target_date, status, started_at, finished_at, error_message, created_at`; `check` de los 4 estados y de que solo los finales tienen `finished_at`; índice `(job_name, target_date)`. | Lo que pide el modelo de datos; la BD impide estados incoherentes. |
| J3 | **Lock = estado `processing`**, con el índice único parcial `job_runs_single_processing_idx (job_name) where status = 'processing'`. La transición pending → processing es un `UPDATE` que la BD rechaza si ya hay otra fila `processing`. | Hace atómica la toma del lock entre dos instancias que arrancan a la vez sin añadir otro mecanismo: el índice restringe el propio estado. |
| J4 | Idempotencia: si existe `completed` para `(nightly_export, target_date)`, no se exporta ni se lanza el pipeline. Un día `failed` se reintenta. | `job_name` solo no basta: el día es la clave. |
| J5 | Las omisiones detectadas **antes** de crear la fila (lock tomado, día ya completado) solo dejan una línea `INFO` en el log y salen con código 0. Si una instancia pierde la carrera **después** de crear su fila, la cierra en `failed` con `Aborted: …` (nunca `pending`). | "Aborta silenciosamente y registra la cancelación" sin llenar `job_runs` de filas sin trabajo; una fila creada siempre termina en un estado final. |
| J6 | Pipeline: entry point real del Hito 6, `python -m data.pipelines.pipeline` (no existe `telemetry_kpi_daily` ni `--no-prefect`). Noche normal: `--trigger scheduled` (4 últimas semanas cerradas, carga idempotente por upsert). Con `TARGET_DATE`: `--week-start <lunes de esa semana> --trigger backfill`. Timeout 3600 s. | La semana en curso nunca entra sola en el reporte (D3/D11 del diseño del pipeline); el backfill permite reprocesar días concretos. |
| J7 | Disparador: **crontab del SO**, `15 1 * * *` (01:15 UTC). En producción, el mismo crontab en un contenedor scheduler dedicado. | Proceso distinto de uvicorn; sin proceso de larga vida extra; en el Codespace no se construye otra imagen por falta de disco. |
| J8 | CSV: día UTC `[00:00, 24:00)`, columnas `id, timestamp, service, event_type, level, value, message, tags` (tags en JSON), cabecera aunque no haya filas; se escribe en `.csv.tmp` y se renombra con `os.replace`. Los CSV quedan fuera de git (`data/raw/telemetry_*.csv`). | Un CSV a medias nunca se da por bueno; datos de runtime que crecen cada día y llevan identificadores de sesión. |
| J9 | Sin zombis: `except BaseException` (incluye `SystemExit` por SIGTERM y `KeyboardInterrupt`) → `failed` + relanzar; `finally` reintenta el cierre; SIGTERM se convierte en `SystemExit`; filas `processing` de más de 120 min (> timeout del pipeline) se cierran como `StaleRun` al arrancar. | SIGKILL o un apagón no se pueden capturar: sin la recuperación, esa fila bloquearía el job para siempre. |
| J10 | `services/job_runner.py` (estado) + `scripts/nightly_export.py` (trabajo). Engine propio del pipeline (`data/pipelines/config.py`). Logs a stdout con formato `ts | nivel | job= | status= | target_date= | run_id= | mensaje`; cron los añade a `logs/nightly_export.log` (fuera de git). Tests con SQLite en memoria. | Lo que pide el ticket; sin importar FastAPI; los tests prueban el índice parcial real sin Supabase. |

## 3. Hallazgos

| # | Hallazgo |
|---|---|
| H1 | El pipeline del Hito 6 se ejecuta con Prefect en modo efímero desde el CLI (`data/pipelines/pipeline.py`); no hay modo `--no-prefect`. |
| H2 | El pipeline tiene su propio control de concurrencia en `pipeline_runs` (advisory lock + `running`/`stale_run`). Si ya hay una corrida suya viva, devuelve `Cancelled` y el CLI termina con código ≠ 0: el job nocturno queda `failed` y se reintenta la noche siguiente. |
| H3 | `telemetry_events` es inmutable (triggers): el snapshot del día es estable, salvo eventos que lleguen tarde con `timestamp` de captura de ese día. |
| H4 | `services/` no tiene `__init__.py` (paquete de espacio de nombres); `services/api/database.py` abre TinyDB al importarse, por eso el script no toca `services/api`. |
| H5 | No se añaden endpoints: `tests/test_serialization_contracts.py` no cambia. |

## 4. Ficheros

- Nuevos: `services/sql/001_job_runs.sql`, `services/job_runner.py`, `scripts/nightly_export.py`, `tests/test_job_runner.py`, `tests/test_nightly_export.py`, `infra/cron/nightly_export.crontab`, `infra/cron/README.md`, `prompts/nightly-export/prompt.md`, este plan.
- Modificados: `.gitignore`, `scripts/README.md`, `scripts/README.es.md`, `prompts/README.md`, `memory-bank/progress.md`.
- Evidencias (Fase 6): `docs/nightly-export/verification.md`.

## 5. Fases

### Fase 0 — Plan
| # | Acción | Commit |
|---|---|---|
| 0.1 | Plan y prompt. | `docs: añadir plan por fases y prompt del script nocturno de telemetría` |
| 0.2 | Fila en `prompts/README.md`. | `docs: registrar el proyecto del script nocturno en el índice de prompts` |

### Fase 1 — Modelo de datos
| # | Acción | Commit |
|---|---|---|
| 1.1 | `services/sql/001_job_runs.sql`. | `feat: añadir la tabla job_runs con su máquina de estados y el lock por processing` |

**Marisin:** ejecutar el SQL en Supabase (SQL Editor) y comprobar la tabla.

### Fase 2 — Control de estado
| # | Acción | Commit |
|---|---|---|
| 2.1 | `services/job_runner.py`. | `feat: añadir el servicio job_runner para el control de estado de job_runs` |
| 2.2 | `tests/test_job_runner.py`. | `test: añadir los tests de la máquina de estados, el lock y la idempotencia de job_runs` |

### Fase 3 — Script
| # | Acción | Commit |
|---|---|---|
| 3.1 | `scripts/nightly_export.py`. | `feat: añadir el script nocturno de exportación de telemetría y lanzamiento del pipeline` |
| 3.2 | `tests/test_nightly_export.py`. | `test: añadir los tests del script nocturno` |
| 3.3 | `.gitignore`: CSV de `data/raw/` y `logs/`. | `chore: ignorar los CSV nocturnos y los logs del job` |

### Fase 4 — Disparador
| # | Acción | Commit |
|---|---|---|
| 4.1 | `infra/cron/nightly_export.crontab` y `README.md`. | `feat: añadir el crontab del script nocturno` |

### Fase 5 — Documentación
| # | Acción | Commit |
|---|---|---|
| 5.1 | `scripts/README.md` y `README.es.md`. | `docs: documentar el script nocturno en scripts/` |
| 5.2 | `progress.md`. | `docs: actualizar progress.md con el script nocturno de telemetría` |

### Fase 6 — Verificación (Marisin)
1. `python -m pytest tests/test_job_runner.py tests/test_nightly_export.py -q` → **30 passed**; `python -m pytest -q` → **178 passed** (148 + 30).
2. Éxito: `python scripts/nightly_export.py` (ayer UTC) y `head -5 data/raw/telemetry_<ayer>.csv`.
3. Idempotencia: repetir el mismo comando → `status=skipped … omisión por duplicado`.
4. Lock: dos instancias a la vez con el mismo `TARGET_DATE`.
5. Fallo: `NIGHTLY_EXPORT_PIPELINE_TIMEOUT_SECONDS=1` → `failed`, código 1; relanzar sin la variable → `completed` (el CSV no se reescribe).
6. SIGTERM: `kill` de una ejecución en curso → `failed` con `SystemExit: 143`.
7. SQL: `job_runs` sin filas `processing`; `pipeline_runs` con sus corridas `backfill`/`scheduled`.
8. Cron: instalación, prueba de cada minuto y crontab definitivo.

| # | Acción | Commit |
|---|---|---|
| 6.1 | `docs/nightly-export/verification.md` con las salidas. | `docs: añadir la verificación del script nocturno` |

## 6. Checklist final

- [ ] `job_runs` creada en Supabase con índice `(job_name, target_date)` y el índice parcial de `processing`.
- [ ] `services/job_runner.py` con `create_run`, `mark_processing`, `mark_completed`, `mark_failed`, `has_processing_lock`, `has_completed_for_date`, `recover_stale_runs`, `run_job`.
- [ ] `python scripts/nightly_export.py` exporta el CSV, lanza el pipeline y deja `completed`.
- [ ] Segunda ejecución del mismo día: omisión por duplicado, sin CSV ni pipeline nuevos.
- [ ] Dos instancias a la vez: la segunda aborta en silencio.
- [ ] Fallo y SIGTERM: fila en `failed` con el mensaje; ninguna `processing`.
- [ ] `TARGET_DATE` funciona sin tocar código.
- [ ] Logs con timestamp, job y estado.
- [ ] Crontab instalado; expresión `15 1 * * *` documentada.
- [ ] `python -m pytest -q` en verde.
- [ ] PR hacia `feature/pipeline-subflows` (o `main` cuando se mergee la cadena) con cron, logs, CSV y etiqueta `cronjob`.
