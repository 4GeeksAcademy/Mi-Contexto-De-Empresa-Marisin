# Plan por fases — Colas de mensajes y tareas asíncronas (TrackFlow)

> **Proyecto 4Geeks:** "Colas de Mensajes y Tareas Asíncronas" — Ticket #DEV-55, *Cola de tareas asíncronas con Redis y Celery*.
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Ubicación de este plan:** `memory-bank/history/2026-11-19_async-tasks.md`. Prompt en `prompts/async-tasks/prompt.md`.
> **Rama:** `feature/async-tasks`, creada por Marisin **desde `feature/nightly-export`** (`db7e61f`; PR #19–#24 pendientes: la operación que se convierte en tarea es el pipeline, que solo existe en esa cadena). Cadena: `main ← #19 ← #20 ← #21 ← #22 ← #23 ← #24 ← esta`.
> **Ejecución:** sin agente en el Codespace. Claude implementa y entrega un parche (`git am`); Marisin añade las dependencias con `uv add`, ejecuta el SQL en Supabase, Docker, pytest, el worker, la API, las pruebas y el push.
> **Etiqueta del PR:** `async-tasks`.

---

## 0. Reglas

1. Un commit por acción, prefijo convencional y descripción en español.
2. Git solo en local para quien implementa; Marisin crea la rama, aplica los parches y hace push.
3. Nada de `git add .` / `-A` / `git add data/`; el JSON local de TinyDB de proveedores nunca se nombra ni se commitea; `.env` no se lee ni se commitea (solo `.env.example`).
4. Las dependencias (`celery`, `redis`, `flower`) las añade Marisin con `uv add`, en su propio commit, antes de aplicar el parche. El parche no toca `pyproject.toml` ni `uv.lock`; sí `services/requirements.txt` (imagen Docker de la API y del worker).
5. El worker nunca corre dentro de uvicorn: ni hilos, ni `BackgroundTasks`, ni lifespan.
6. Los logs de las pruebas se copian de `logs/` (ignorado) a `docs/async-tasks/evidencias/`.

---

## 1. Rúbrica (resumen)

- Redis en Docker (imagen oficial, :6379, `noeviction`) como broker; API y workers al mismo Redis vía `REDIS_URL`.
- La operación que más tarda se convierte en tarea de Celery; su endpoint responde **202** con `task_id` en < 200 ms.
- `GET /tasks/{task_id}` → `{task_id, status, result}` con `pending`, `started`, `success`, `failure`.
- `max_retries=3` con backoff exponencial; al agotarlos, DLQ en BD con `task_id`, intento, error y timestamp.
- Workers en procesos separados: detener la API no detiene el worker ni pierde mensajes.
- Mensajes con identificadores, nunca payloads voluminosos. ACK tras éxito. Timeout en toda tarea.
- Logs por tarea: `task_id`, intento, estado y duración; los fallos, el error completo.
- Flower en Docker (:5555) mostrando al menos una tarea completada y una fallida.
- README: cómo levantar y detener el worker.
- PR: endpoint elegido y justificación, captura de Flower (completada + DLQ), log de una ejecución con reintento, etiqueta `async-tasks`.

## 2. Decisiones (A1–A12)

| # | Decisión | Por qué |
|---|---|---|
| A1 | La operación es `POST /reporting/pipeline-runs` (corrida manual del pipeline). | Es la más pesada (extracción de 4 semanas, Pandas, upsert, snapshot; ~1,5 s hoy y minutos con los reintentos de Prefect) y hasta ahora corría en un hilo **dentro** de FastAPI, que moría con cada reinicio de uvicorn. |
| A2 | `services/celery_app.py` con `app = Celery(...)`; broker y result backend = `REDIS_URL` (por defecto `redis://localhost:6379/0`; en Docker `redis://redis:6379/0`). | Lo que pide el ticket; mismo Redis para API y workers. |
| A3 | El productor publica con `send_task` **por nombre** (`trackflow.reporting.run_pipeline`): la API no importa `services/tasks.py` ni Prefect. Nombres de tarea fijos, independientes de la ruta del módulo. | Desacopla productor y consumidor; funciona igual en el Codespace (`services.tasks`) y en el contenedor (`tasks`). |
| A4 | Mensaje = `{week_start, triggered_by}` y el `task_id` lo genera la API (`uuid4`). El primer intento usa `run_id = task_id` en `reporting.pipeline_runs`; cada reintento, `uuid5(task_id, "attempt-N")`. | Mensajes ligeros; la API puede devolver `task_id` y `run_id` sin esperar; cada intento deja su propia fila sin chocar con la clave primaria. |
| A5 | El `POST` ya **no consulta la BD** (antes comprobaba la corrida activa para devolver 409). La concurrencia la sigue resolviendo `open_pipeline_run` en el worker: el flow termina en `Cancelled` y la tarea en `SUCCESS` con `pipeline_status = "cancelled"`, sin reintentar. | El request solo publica en Redis: < 200 ms garantizado aunque Supabase o Prefect tarden (`load_config()` intenta leer un block de Prefect). Contrato: 202 / 403 / 422 / 503. |
| A6 | `max_retries=3`, `countdown = 5 · 2^reintentos` → 5 s, 10 s, 20 s (base configurable con `TRACKFLOW_TASK_RETRY_BASE_SECONDS`). Reintento explícito con `self.retry`. | Backoff exponencial visible en el log; tres reintentos = cuatro intentos. |
| A7 | DLQ en dos piezas: al agotar los reintentos, `run_pipeline` publica un mensaje en la cola **`dead_letter`**; la tarea `trackflow.dead_letter.record` lo consume y lo persiste en **`public.task_dead_letters`** (`services/sql/002_task_dead_letters.sql`), idempotente por `task_id`, con sus propios reintentos ante errores de BD. | Es una cola de verdad (se ve en Flower) y el registro queda en BD como pide la rúbrica. |
| A8 | `GET /tasks/{task_id}` (con sesión, `task_id` UUID) devuelve `{task_id, status, celery_state, result, error}`. `status` ∈ {`pending`, `started`, `success`, `failure`}; `RETRY` → `pending`; `celery_state` es el estado real de Celery. `error` = `Tipo: mensaje`, sin traza. 503 si Redis no responde. | Los cuatro estados del ticket sin ocultar el estado real. |
| A9 | Configuración: `task_acks_late`, `task_reject_on_worker_lost`, `worker_prefetch_multiplier=1`, `task_track_started`, `visibility_timeout=3600`, timeouts globales 600/660 s y por tarea (`run_pipeline` 600/660 s, `record_dead_letter` 30/60 s), eventos para Flower (`worker_send_task_events`, `task_send_sent_event`), `broker_connection_timeout=2` y publicación sin reintentos. | Las tres reglas del patrón y una API que no se cuelga si Redis cae. |
| A10 | Logs con las señales de Celery (`task_prerun`, `task_postrun`, `task_retry`, `task_failure`) en el logger `trackflow.tasks`: `task_id`, `attempt`, `state`, `duration_ms`; los fallos, tipo, mensaje y traza. | Genérico para todas las tareas, sin repetir código en cada una. |
| A11 | Docker: servicio `redis` (`redis:7-alpine`, `--maxmemory 256mb --maxmemory-policy noeviction --appendonly yes`, volumen, healthcheck), `flower` (`mher/flower:2.0`, :5555) y `worker` (misma imagen que la API). En el Codespace, el worker corre como **proceso local** y solo se levantan `redis` y `flower`. | Imágenes pequeñas; el Codespace va justo de disco y no se reconstruye la imagen de la API. |
| A12 | Fallo simulado para la demo de la DLQ: `TRACKFLOW_TASKS_FORCE_FAILURE=1` en el entorno del worker. | Prueba reintentos y DLQ sin tocar la BD ni el contrato de la API. |

## 3. Hallazgos

| # | Hallazgo |
|---|---|
| H1 | `data/pipelines/triggers.py` lanzaba el flow con `threading.Thread(daemon=True)` dentro de uvicorn. Se sustituye por `run_manual_flow()`, que llama al flow con `return_state=True` y traduce `Completed` / `Cancelled` / fallo. |
| H2 | `services/` no tiene `__init__.py` (paquete de espacio de nombres) y en Docker `/app` es `services/`: los imports nuevos repiten el patrón `try: from services… except ModuleNotFoundError: from …`. |
| H3 | `services/api/database.py` abre TinyDB al importarse: el worker no importa nada de `services/api/` (usa el engine del pipeline, `data/pipelines/config.py`). |
| H4 | `tests/test_serialization_contracts.py` cuenta las rutas: 36 → **37** por `GET /tasks/{task_id}`. |
| H5 | Celery devuelve `PENDING` para un `task_id` que no existe; no se distingue sin guardar más estado, y se documenta. |

## 4. Ficheros

Nuevos: `services/celery_app.py`, `services/tasks.py`, `services/dead_letter.py`, `services/sql/002_task_dead_letters.sql`, `services/api/routes/tasks.py`, `tests/test_async_tasks.py`, `docs/async-tasks/README.md`, `prompts/async-tasks/prompt.md`, este plan.
Modificados: `data/pipelines/triggers.py`, `data/pipelines/PIPELINE_DESIGN.md`, `services/reporting/router.py`, `services/reporting/schemas.py`, `services/api/main.py`, `services/requirements.txt`, `docker-compose.yml`, `.env.example`, `README.md`, `README.es.md`, `tests/test_reporting_routes.py`, `tests/test_serialization_contracts.py`, `prompts/README.md`, `memory-bank/progress.md`.
De Marisin: `pyproject.toml` y `uv.lock` (`uv add`), `.env` (sin commitear), `docs/async-tasks/verification.md` y `docs/async-tasks/evidencias/` al final.

## 5. Fases

### Fase 0 — Rama y dependencias (Marisin)

| # | Acción | Commit |
|---|---|---|
| 0.1 | `git checkout feature/nightly-export && git checkout -b feature/async-tasks` | — |
| 0.2 | `uv add celery redis flower` | `chore: añadir celery, redis y flower` (`pyproject.toml`, `uv.lock`) |

### Fase 1 — Implementación (Claude, parche)

| # | Acción | Commit |
|---|---|---|
| 1.1 | Plan y prompt | `docs: añadir plan por fases y prompt de la cola de tareas asíncronas` |
| 1.2 | Fila en el índice | `docs: registrar el proyecto de la cola de tareas en el índice de prompts` |
| 1.3 | Redis, Flower y worker en Compose; `REDIS_URL` | `feat: añadir Redis, Flower y el worker de Celery a docker-compose` |
| 1.4 | App de Celery | `feat: añadir la app de Celery con Redis como broker y backend` |
| 1.5 | Tabla de la DLQ | `feat: añadir la tabla task_dead_letters de la Dead Letter Queue` |
| 1.6 | Módulo de la DLQ | `feat: añadir el registro idempotente de la Dead Letter Queue` |
| 1.7 | Flow desde la cola | `refactor: ejecutar la corrida manual del pipeline desde la cola en lugar de un hilo` |
| 1.8 | Tareas | `feat: añadir las tareas run_pipeline y record_dead_letter con reintentos y DLQ` |
| 1.9 | Endpoint 202 | `feat: encolar la corrida manual del pipeline y responder 202 con task_id` |
| 1.10 | Endpoint de estado | `feat: añadir GET /tasks/{task_id} con el estado de la tarea` |
| 1.11 | Tests | `test: añadir los tests de la cola de tareas y adaptar los de reporting` |
| 1.12 | Docs | `docs: documentar la cola de tareas y cómo levantar y detener el worker` |
| 1.13 | Registro | `docs: actualizar progress.md con la cola de tareas asíncronas` |

### Fase 2 — Verificación (Marisin, guiada por Claude)

| # | Acción | Evidencia |
|---|---|---|
| 2.1 | `git am` del parche; SQL `002_task_dead_letters.sql` en Supabase | columnas e índices |
| 2.2 | `python -m pytest -q` | N passed |
| 2.3 | `docker compose up -d redis flower`; `redis-cli ping` y `config get maxmemory-policy` | `PONG`, `noeviction` |
| 2.4 | Worker (`celery -A services.celery_app worker -l info`) y API en terminales separadas | `celery@… ready`, colas `celery` y `dead_letter` |
| 2.5 | `POST /reporting/pipeline-runs` con `curl -w '%{time_total}'`; `GET /tasks/{id}` varias veces | 202 < 200 ms; `pending/started` → `success` |
| 2.6 | Worker con `TRACKFLOW_TASKS_FORCE_FAILURE=1`; `POST`; `GET` hasta `failure`; `select` en `task_dead_letters` | log con 3 reintentos (5/10/20 s) y fila en la DLQ |
| 2.7 | Worker parado → `POST` → parar la API → arrancar el worker → la tarea se ejecuta | mensaje no perdido |
| 2.8 | Captura de Flower (Tasks: una `SUCCESS` y una `FAILURE` + la `record_dead_letter`) | PNG |
| 2.9 | `docs/async-tasks/verification.md` + logs en `evidencias/` | commits `docs:` |

🛑 STOP tras cada paso de la Fase 2 si algo no coincide: pegar la salida a Claude.

### Fase 3 — PR

Push, PR `feature/async-tasks` → base `feature/nightly-export`, título "Cola de tareas asíncronas con Redis y Celery", etiqueta `async-tasks`.

## 6. Checklist final

- [ ] Redis en Docker, `noeviction`, :6379; Flower en :5555.
- [ ] `REDIS_URL` en API y worker; `.env.example` actualizado.
- [ ] 202 + `task_id` en < 200 ms.
- [ ] `GET /tasks/{task_id}` con los cuatro estados.
- [ ] 3 reintentos con backoff 5/10/20 s; DLQ en `task_dead_letters` con `task_id`, intento, error y timestamp.
- [ ] Worker separado; parar la API no pierde mensajes.
- [ ] Mensajes solo con referencias.
- [ ] Logs con `task_id`, intento, estado, duración y error completo.
- [ ] README: levantar y detener el worker.
- [ ] PR con justificación, captura de Flower, log con reintento y etiqueta.
