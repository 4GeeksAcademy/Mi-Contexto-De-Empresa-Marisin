# Plan por fases — Data Pipeline 2/3: Pipeline de Desempeño de Negocio Resiliente (TrackFlow)

> **Proyecto 4Geeks:** "Hito — Pipeline de Desempeño de Negocio Resiliente (Parte 2 de 3)".
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Ubicación de este plan:** `memory-bank/history/2026-11-19_pipeline-implementation.md`. Prompt en `prompts/pipeline-implementation/prompt.md`.
> **Rama:** `feature/pipeline-implementation`, creada por Marisin **desde `feature/pipeline-design`** (PR #19, #20 y #21 pendientes). Cadena: `main ← #19 ← #20 ← #21 ← esta`.
> **Ejecución:** Claude implementa y entrega un parche (`git am`); Marisin crea las tablas en Supabase, ejecuta pytest, el pipeline, la API y el push.
> **Commit del entregable:** el del flow principal lleva el mensaje exacto del enunciado, `feat: implement resilient business performance pipeline`.

---

## 0. Reglas

1. Un commit por acción, prefijo convencional y descripción en español (salvo el commit del entregable).
2. Git solo en local para quien implementa; Marisin crea la rama, aplica los parches y hace push.
3. Nada de `git add .` / `-A`; el JSON local de TinyDB de proveedores nunca se nombra ni se commitea (vive en `data/`: añadir siempre rutas explícitas); ningún `.env*` se lee ni se edita.
4. `telemetry_events`, `services/telemetry/analysis.py` y `GET /telemetry/report` no se tocan. El pipeline lee `telemetry_events` solo con `select`.
5. Dependencias: `prefect>=3` lo instaló Marisin con `uv add` (commit `chore: añadir prefect 3 a las dependencias del proyecto`, Prefect 3.9.3). El parche solo lo añade a `services/requirements.txt` para la imagen de Docker.

---

## 1. Rúbrica (resumen)

- `data/pipelines/pipeline.py` con ≥ 1 flow y ≥ 3 tasks, ejecutable con `python data/pipelines/pipeline.py`.
- `retries` > 0 con comentario que justifica el número en las tasks con servicios externos.
- ≥ 1 task opcional invocada con `return_state=True`; el flow sigue si falla. ≥ 1 fallo manejado explícitamente con `return_state=True`.
- Caché (`cache_key_fn` + `cache_expiration`) en una task de transformación, con comentario sobre la clave y la duración.
- Carga idempotente apoyada en `unique (warehouse, client_id, week_start)`.
- ≥ 5 campos de metadata por corrida (inicio, fin, registros procesados, estado, errores).
- Comando y frecuencia documentados en `PIPELINE_DESIGN.md`.
- 3 endpoints en `services/reporting/` (estado de la última corrida, disparo manual, filas de KPIs con el contrato del BRIEFING) que importan de `data/pipelines/`.
- KPIs exactamente como en "KPIs a medir" del BRIEFING; código consistente con el diseño.

## 2. Decisiones (D12–D22, continúan las del diseño)

| # | Decisión | Por qué |
|---|---|---|
| D12 | Módulos planos en `data/pipelines/` (`pipeline.py`, `config.py`, `extract.py`, `load.py`, `runs.py`, `queries.py`, `triggers.py`) en lugar de la subcarpeta prevista en el diseño. | El enunciado fija `data/pipelines/pipeline.py` como punto de entrada. El diseño §13.3 se actualiza. |
| D13 | `data/`, `data/pipelines/` y `data/process/` pasan a ser paquetes (`__init__.py`). `pipeline.py` añade la raíz del repo al `sys.path` cuando se ejecuta como script. | `python data/pipelines/pipeline.py` solo pone `data/pipelines/` en el path; así funcionan igual el CLI, pytest y la API. |
| D14 | Caché en `transform_weekly_kpis` con clave = huella del contenido extraído + `excluded_user_ids` + `TRANSFORM_VERSION`, válida 1 h. Extracción sin caché. | Cumple "si ya corrió en la última hora no se repite" sin servir resultados viejos: un evento tardío cambia la huella. |
| D15 | Etapas críticas invocadas con `return_state=True` y `_required()`: registran `failed` en `pipeline_runs` y detienen el flow. | Fallo manejado explícitamente y log siempre cerrado. |
| D16 | Dos tasks opcionales: `check_capture_coverage` (cobertura frente a `stock_entries`/`stock_exits`) y `export_eval_snapshot` (`data/eval/snapshots/`, ignorado por git). | Ninguna sostiene los KPIs: si fallan, solo añaden un aviso. |
| D17 | Upsert con `jsonb_to_recordset` en una sola sentencia y `returning (xmax = 0)` para contar inserciones y actualizaciones. | Una transacción, conteos exactos de `rows_*` y SQL probado en PostgreSQL 16. |
| D18 | `heartbeat_pipeline_run` tras extracción, transformación y validación. | Checkpoint `last_completed_phase` del diseño §11.1. |
| D19 | El disparo manual lanza el flow en un hilo y responde `202 {run_id, status: "pending"}`; 409 si hay corrida viva; solo `admin`/`manager`. | Respuesta inmediata sin duplicar lógica: el hilo ejecuta el mismo flow que el CLI. |
| D20 | Los endpoints usan el `engine` de la API (`services/api/database.py`); el flow, el suyo (`config.get_engine`, mismas opciones). | Mismas convenciones que el resto de la API; el pipeline también corre sin la API. |
| D21 | `docker-compose.yml` monta `./data` en `/app/data`. | El contenedor solo veía `services/` (H6 del diseño). |
| D22 | Por defecto el CLI recalcula las 4 semanas **cerradas**; para la semana en curso se usa `--week-start`. | D11 del diseño. Los eventos reales son de la semana del 2026-11-16, que hoy está en curso. |

## 3. Hallazgos para confirmar

| # | Hallazgo |
|---|---|
| H8 | `tests/test_serialization_contracts.py` pasa de 33 a 36 rutas. |
| H9 | `data/` contiene el JSON local de TinyDB (ignorado): nunca `git add data/`. |
| H10 | Prefect arranca un servidor temporal la primera vez que corre un flow sin `PREFECT_API_URL` (tarda unos segundos). |

## 4. Fases

### Fase 0 — Plan
| # | Acción | Commit |
|---|---|---|
| 0.1 | Plan y prompt. | `docs: añadir plan por fases y prompt de la implementación del pipeline de negocio` |
| 0.2 | Fila en `prompts/README.md`. | `docs: registrar el proyecto de implementación del pipeline en el índice de prompts` |

### Fase 1 — Esquema y transformación
| # | Acción | Commit |
|---|---|---|
| 1.1 | `data/pipelines/sql/001_reporting_schema.sql`. | `feat: añadir el esquema reporting del pipeline de negocio` |
| 1.2 | `data/process/weekly_kpis.py` + paquetes `data/`. | `feat: añadir la transformación de KPIs semanales por almacén y cliente` |
| 1.3 | `tests/test_weekly_kpis.py`. | `test: cubrir los KPIs semanales del pipeline de negocio` |

**Marisin:** ejecutar el SQL en Supabase y comprobar las tablas.

### Fase 2 — Extracción, carga y log
| # | Acción | Commit |
|---|---|---|
| 2.1 | `config.py` (blocks, configuración, engine). | `feat: añadir la configuración y la conexión del pipeline de negocio` |
| 2.2 | `extract.py`. | `feat: añadir la extracción de solo lectura desde telemetry_events` |
| 2.3 | `load.py`. | `feat: añadir la carga idempotente con upsert en reporting` |
| 2.4 | `runs.py`. | `feat: añadir el log de corridas en reporting.pipeline_runs` |

### Fase 3 — Flow de Prefect
| # | Acción | Commit |
|---|---|---|
| 3.1 | `data/pipelines/pipeline.py`. | `feat: implement resilient business performance pipeline` |
| 3.2 | `tests/test_pipeline_flow.py`. | `test: cubrir la resiliencia del flow de Prefect` |
| 3.3 | `prefect>=3` en `services/requirements.txt`. | `chore: añadir prefect a las dependencias del contenedor de la API` |
| 3.4 | `./data` montado en el contenedor. | `chore: montar data en el contenedor de la API` |

**Marisin:** `python -m pytest -q`; `python data/pipelines/pipeline.py --week-start 2026-11-16` dos veces; `python data/pipelines/pipeline.py`.

### Fase 4 — Endpoints
| # | Acción | Commit |
|---|---|---|
| 4.1 | `queries.py` y `triggers.py`. | `feat: añadir las consultas y el disparo manual del pipeline` |
| 4.2 | `services/reporting/` y router en `main.py`. | `feat: añadir los endpoints de services/reporting` |
| 4.3 | `tests/test_reporting_routes.py`. | `test: cubrir los endpoints de reporting` |
| 4.4 | Contrato de rutas 33 → 36. | `test: actualizar el contrato de rutas con los endpoints de reporting` |

**Marisin:** uvicorn, token con `admin@test.com` y `curl` a los tres endpoints.

### Fase 5 — Documentación y cierre
| # | Acción | Commit |
|---|---|---|
| 5.1 | `.gitignore` de `data/eval/snapshots/`. | `chore: ignorar los snapshots de eval del pipeline` |
| 5.2 | `PIPELINE_DESIGN.md`: estado, tasks reales, estructura y §15 (frecuencia y comandos). | `docs: documentar la ejecución y la frecuencia del pipeline de negocio` |
| 5.3 | `progress.md`. | `docs: actualizar progress.md con la implementación del pipeline de negocio` |
| 5.4 | **Marisin:** evidencias reales (salida del CLI, consulta en Supabase y respuestas de la API). | `docs: añadir la verificación del pipeline de negocio con datos reales` |

## 5. Checklist final

- [ ] `pipeline.py` con 1 flow y 9 tasks; `python data/pipelines/pipeline.py` sin errores.
- [ ] `retries` justificados en extracción, carga y control de corrida.
- [ ] `check_capture_coverage` y `export_eval_snapshot` con `return_state=True`; las críticas también, con `_required()`.
- [ ] Caché en `transform_weekly_kpis` (`cache_key_fn`, 1 h) con comentario.
- [ ] Segunda corrida sobre los mismos datos: `rows_inserted = 0`, `rows_updated = 0`.
- [ ] `reporting.pipeline_runs` con inicio, fin, registros, estado y errores.
- [ ] Comando y frecuencia en `PIPELINE_DESIGN.md` §15.
- [ ] 3 endpoints en `services/reporting/` importando de `data/pipelines/`; KPIs con el JSON del BRIEFING.
- [ ] `telemetry_events`, `analysis.py` y `GET /telemetry/report` intactos.
