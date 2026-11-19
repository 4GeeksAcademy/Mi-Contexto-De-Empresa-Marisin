# Cola de tareas asíncronas con Redis y Celery (Ticket #DEV-55)

```
Cliente ──POST /reporting/pipeline-runs──▶ API (productor) ──send_task──▶ Redis (broker)
   │                                         │ 202 {task_id}                  │
   │                                         ▼                                ▼
   └──GET /tasks/{task_id}──▶ API ──AsyncResult──▶ Redis (backend) ◀── worker Celery (consumidor)
                                                                          │  run_pipeline (3 reintentos, backoff)
                                                                          │  └─ agota reintentos ─▶ cola dead_letter
                                                                          ▼                         │
                                                              reporting.* (Supabase)   record_dead_letter
                                                                                                    ▼
                                                                                public.task_dead_letters
```

## Operación elegida y por qué

`POST /reporting/pipeline-runs` (corrida manual del Pipeline de Desempeño de Negocio)
es la operación más pesada de la API: extrae las 4 últimas semanas de `telemetry_events`
de Supabase, transforma con Pandas, hace upsert en `reporting.weekly_warehouse_client_performance`
y exporta un snapshot. Cada corrida tarda del orden de 1,5 s con los datos actuales
(`docs/pipeline/business-pipeline-verification.md`) y crece con el volumen de eventos y
con los reintentos internos de Prefect (hasta minutos si Supabase falla). Además, hasta
este ticket se ejecutaba en un **hilo dentro del proceso de FastAPI**: si uvicorn se
reiniciaba (`--reload`, despliegue), la corrida moría con él. El resto de endpoints son
lecturas o escrituras de una fila, y `GET /telemetry/report` ya tiene caché de 60 s.

## Piezas

| Pieza | Fichero | Qué hace |
|---|---|---|
| App de Celery | `services/celery_app.py` | Broker y backend = `REDIS_URL`; ACK tardío, `reject_on_worker_lost`, timeouts, eventos para Flower, colas `celery` y `dead_letter`; productor `enqueue_pipeline_run()`; logs por señal. |
| Tareas | `services/tasks.py` | `trackflow.reporting.run_pipeline` (`max_retries=3`, countdown 5/10/20 s) y `trackflow.dead_letter.record` (consumidor de la DLQ). Solo las importa el worker. |
| DLQ persistida | `services/dead_letter.py` + `services/sql/002_task_dead_letters.sql` | Fila por tarea fallida: `task_id`, `attempt`, `max_retries`, `error_type`, `error_message`, `task_kwargs`, `failed_at`, `recorded_at`. Idempotente por `task_id`. |
| Productor | `services/reporting/router.py` | `POST /reporting/pipeline-runs` → `202 {task_id, run_id, status, week_start}`; 503 si Redis no responde. No toca la BD. |
| Estado | `services/api/routes/tasks.py` | `GET /tasks/{task_id}` → `{task_id, status, celery_state, result, error}`. |
| Flow | `data/pipelines/triggers.py` | `run_manual_flow()` ejecuta el mismo flow que el cron y el CLI y traduce su state (`completed`, `cancelled`, `failed`). |
| Infra | `docker-compose.yml` | `redis` (7-alpine, `noeviction`, AOF, :6379), `flower` (:5555) y `worker` (despliegue en contenedor). |

## Mensajes ligeros

El mensaje de `run_pipeline` es `{"week_start": "2026-11-16" | null, "triggered_by": "1"}`.
El worker lee los eventos de Supabase él mismo. El de la DLQ lleva el `task_id`, el
intento, el tipo y el mensaje del error (≤ 4000 caracteres), esas mismas referencias y
la hora del fallo.

## Estados

| `celery_state` | `status` | Cuándo |
|---|---|---|
| `PENDING` | `pending` | En la cola. Celery también devuelve `PENDING` para un id que no conoce. |
| `STARTED` | `started` | Un worker la ejecuta (`task_track_started=True`). |
| `RETRY` | `pending` | Falló un intento y espera su countdown; `error` trae el último error. |
| `SUCCESS` | `success` | `result` = `{pipeline_status, run_id, attempt, week_start, summary}`. `pipeline_status = "cancelled"` si ya había otra corrida viva (antes, 409). |
| `FAILURE` | `failure` | Agotó los 3 reintentos (4 intentos) y está en la DLQ; `error` = `Tipo: mensaje`. |

## Reintentos, ACK y timeouts

- `max_retries=3` con `countdown = 5 · 2^n` → 5 s, 10 s y 20 s entre intentos. Cada intento
  abre su propia fila en `reporting.pipeline_runs` (`run_id` = `task_id` en el primero).
- `task_acks_late` + `task_reject_on_worker_lost`: el mensaje se confirma al terminar; si
  el worker muere a mitad, Redis lo reentrega (visibility timeout de 3600 s).
- Timeouts: `run_pipeline` 600 s soft / 660 s hard; `record_dead_letter` 30 / 60 s.
- Fallo simulado para la demo: `TRACKFLOW_TASKS_FORCE_FAILURE=1` en el entorno **del worker**.

## Logs

Logger `trackflow.tasks`, una línea por fase de cada ejecución:

```
task=trackflow.reporting.run_pipeline task_id=… attempt=1 state=STARTED
task=trackflow.reporting.run_pipeline task_id=… attempt=1 state=RETRY next_attempt_in=5s error=…
task=trackflow.reporting.run_pipeline task_id=… attempt=1 state=RETRY duration_ms=3.2
…
task=trackflow.reporting.run_pipeline task_id=… attempt=4 state=FAILURE error=SimulatedTaskFailure: … (+ traza)
task=trackflow.reporting.run_pipeline task_id=… attempt=4 state=FAILURE duration_ms=2.9
DLQ task=trackflow.reporting.run_pipeline task_id=… attempt=4 error=… recorded=inserted
```

## Verificación

Paso a paso con los comandos y las evidencias en [`verification.md`](verification.md).
