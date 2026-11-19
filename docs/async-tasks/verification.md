# Verificación de la cola de tareas asíncronas (Ticket #DEV-55)

Pruebas reales del 19-11-2026 en el Codespace, con Redis y Flower en Docker y la tabla de la DLQ en Supabase. Rama `feature/async-tasks`, creada desde `feature/nightly-export`. Plan y decisiones: [`memory-bank/history/2026-11-19_async-tasks.md`](../../memory-bank/history/2026-11-19_async-tasks.md). Diseño: [`README.md`](README.md).

Las capturas y los logs completos están en [`evidencias/`](./evidencias/). Los logs son copias de `logs/`, que no se versiona.

## 1. Entorno

| Comprobación | Resultado | Evidencia |
|---|---|---|
| `services/sql/002_task_dead_letters.sql` en el SQL Editor de Supabase | `Success`; la consulta de verificación devuelve las **10 columnas** (`id`, `task_id`, `task_name`, `attempt`, `max_retries`, `error_type`, `error_message`, `task_kwargs` jsonb, `failed_at`, `recorded_at`) | `supabase-tabla-columnas.png` |
| `python -m pytest -q` | **201 passed** (178 anteriores + 23 nuevos) | `pytest-201-passed.png` |
| `docker compose up -d redis flower` | `redis:7-alpine` (healthy, :6379) y `mher/flower:2.0` (:5555) en marcha | `redis-noeviction.png` |
| `redis-cli ping` / `config get maxmemory-policy` | `PONG` / `noeviction` | `redis-noeviction.png` |
| Worker `celery -A services.celery_app worker -l info -c 2` | `transport` y `results` = `redis://localhost:6379/0` (`REDIS_URL`), `prefork` con 2 procesos, `task events: ON`, colas `celery` y `dead_letter`, tareas `trackflow.dead_letter.record` y `trackflow.reporting.run_pipeline`, `ready.` | `worker.log` |

API, worker y Redis corren en procesos separados: el worker en su propia terminal, la API con `python -m uvicorn services.api.main:app --port 8000 --reload` en otra y Redis en Docker.

## 2. Pruebas

| # | Prueba | Resultado | Evidencia |
|---|---|---|---|
| 1 | Corrida correcta (`POST /reporting/pipeline-runs` `{"week_start":"2026-11-16"}`) | **202** con `{"task_id":"c525ec3a…","run_id":"c525ec3a…","status":"pending","week_start":"2026-11-16"}`. El worker ejecutó el flow completo y registró `attempt=1 state=SUCCESS duration_ms=22636.7` (incluye el arranque del servidor temporal de Prefect). `GET /tasks/c525ec3a…` → `success` con el resumen (`rows_unchanged: 1`). | `worker.log`, `api-202-y-parada.png` |
| 2 | Tiempo de respuesta del `POST` | Servidor (`X-Response-Time-ms` en el log de la API): **169,0 ms** el primero (abre la conexión con Redis) y **5,3 ms** después. Cliente (`curl`): 0,171 s, 0,0074 s, 0,019 s y 0,0076 s. Siempre < 200 ms, aunque el pipeline tarde de 16 a 22 s. | `api-202-y-parada.png`, `post-202-y-failure.png` |
| 3 | Ciclo de estados (`GET /tasks/{id}` cada segundo, tarea `80884a17…`) | `started` (`celery_state: STARTED`) durante ~8 s y después `success` (`SUCCESS`). | `estados-started-success.png` |
| 4 | Reintentos con backoff (worker con `TRACKFLOW_TASKS_FORCE_FAILURE=1`, tarea `05050b62…`) | Intentos a las 21:01:41, 21:01:46, 21:01:56 y 21:02:16: esperas de **5 s, 10 s y 20 s** (`state=RETRY next_attempt_in=5s/10s/20s`). Intento 4: `reintentos agotados (3): se envía a la DLQ` y `state=FAILURE` con la traza completa. `GET /tasks/05050b62…` → `failure`, `error: "SimulatedTaskFailure: Fallo simulado…"`. | `worker-reintentos-dlq.png`, `post-202-y-failure.png`, `worker_fallo.log` |
| 5 | Dead Letter Queue | El worker consumió la cola `dead_letter`: `DLQ … attempt=4 error=SimulatedTaskFailure … recorded=inserted`; `trackflow.dead_letter.record` en `SUCCESS` (445 ms). En Supabase, `public.task_dead_letters` tiene la fila de `05050b62…`: `task_name = trackflow.reporting.run_pipeline`, `attempt = 4`, `max_retries = 3`, `error_type = SimulatedTaskFailure`, mensaje completo y `failed_at = 2026-11-19 21:02:16`. | `supabase-dlq.png`, `worker_fallo.log` |
| 6 | Parar la API no pierde mensajes (tarea `8d144a89…`) | Worker parado → `POST` 202 → `redis-cli llen celery` = **1** → API parada (`Ctrl+C`) → worker arrancado: recogió la tarea y terminó con `attempt=1 state=SUCCESS duration_ms=16723.6` **con la API apagada** → `llen celery` = **0** → API arrancada de nuevo: `GET /tasks/8d144a89…` → `success`. | `cola-llen-1-y-0.png`, `worker-sin-api.png`, `api-202-y-parada.png`, `task-success-tras-reinicio.png` |
| 7 | Flower | **Tasks:** `run_pipeline` `c525ec3a…` y `80884a17…` en `SUCCESS`, `05050b62…` en `FAILURE` y `dead_letter.record` `7e016e1b…` en `SUCCESS`; la columna `kwargs` solo muestra `{'week_start': '2026-11-16', 'triggered_by': '1'}`. **Workers:** `celery@codespaces-8bfc79` online, 7 procesadas, 1 fallida, 3 completadas y 3 reintentadas. | `flower-tasks.png`, `flower-workers.png` |

## 3. Extracto: ejecución con reintentos (prueba 4)

Simplificado: sin el prefijo `[fecha: NIVEL/ForkPoolWorker-N]` de Celery y con los ids acortados.

```
21:01:41,198 INFO    task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=1 state=STARTED
21:01:41,240 WARNING task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=1 state=RETRY next_attempt_in=5s error=…
21:01:41,240 WARNING task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=1 state=RETRY duration_ms=4…
21:01:46,217 INFO    task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=2 state=STARTED
21:01:46,235 WARNING task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=2 state=RETRY next_attempt_in=10s error=…
21:01:56,223 INFO    task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=3 state=STARTED
21:01:56,240 WARNING task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=3 state=RETRY next_attempt_in=20s error=…
21:02:16,229 INFO    task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=4 state=STARTED
21:02:16,233 ERROR   task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=4 reintentos agotados (3): se envía a la DLQ
21:02:16,247 ERROR   task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=4 state=FAILURE error=SimulatedTaskFailure: Fallo simulado (TRACKFLOW_TASKS_FORCE_FAILURE=1) en el intento 4 de la tarea 05050b62-…
                     Traceback (most recent call last): … services/tasks.py, line 106, in run_pipeline …
21:02:16,249 WARNING task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=4 state=FAILURE duration_ms=20.9
21:02:16,688 ERROR   DLQ task=trackflow.reporting.run_pipeline task_id=05050b62-… attempt=4 error=SimulatedTaskFailure: … recorded=inserted
21:02:16,692 INFO    task=trackflow.dead_letter.record task_id=7e016e1b-… attempt=1 state=SUCCESS duration_ms=445.0
```

El log completo, con la traza de cada intento, está en `evidencias/worker_fallo.log`.

## 4. Checklist de la rúbrica

- [x] Redis en Docker (imagen oficial, :6379, `noeviction`) y workers conectados sin errores.
- [x] `REDIS_URL` común a la API y al worker (`.env.example`).
- [x] `202 Accepted` con `task_id` en < 200 ms, independientemente de la duración de la tarea.
- [x] `GET /tasks/{task_id}` con `pending`, `started`, `success` y `failure`.
- [x] Reintentos con backoff: 5 s, 10 s y 20 s, nunca inmediatos.
- [x] Tras agotar los reintentos, fila en la DLQ con `task_id`, intento, error y timestamp.
- [x] Worker en un proceso separado: parar la API no lo detiene ni pierde mensajes.
- [x] Mensajes con referencias (`week_start`, `triggered_by`), sin payloads voluminosos.
- [x] Logs con `task_id`, intento, estado, duración y, en los fallos, el error completo.
- [x] Flower con tareas completadas y una fallida, más la de la DLQ.
