# Plan por fases — Telemetría 3/3: Almacenamiento (TrackFlow)

> **Proyecto 4Geeks:** "Telemetría de tu compañía – Almacenamiento" (3 de 3).
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Ubicación de este plan:** `memory-bank/history/2026-11-18_telemetry-storage.md`. Prompt en `prompts/telemetry-storage/prompt.md`.
> **Rama:** `feature/telemetry-storage`, creada por Marisin **desde `feature/telemetry-frontend-capture`** (el PR 2 está pendiente de aprobación).
> **Contrato aprobado:** `docs/telemetry/telemetry-plan.md` (en especial §4, §10 y §11) y `docs/telemetry/event-schemas.json`. Los `event_type`, los allowlists, `x-level` y `x-value-property` salen **de ahí**.
> **PR:** título exacto `feat: telemetry event storage`.
> **Ejecución:** el agente local del Codespace (`deepseek-v4-flash`) no superó la primera respuesta, así que Marisin decidió que **Claude implemente cada fase** en su clon y la entregue como parche (`git am`). Las reglas de la §0 se aplican igual; pytest, uvicorn, curl y todo lo que pase en Supabase lo sigue ejecutando Marisin.

---

## 0. Reglas de ejecución para el agente

1. **Una fase cada vez.** Al terminar una fase, el agente se detiene, entrega el resumen de la §9 y no sigue hasta recibir `OK fase N, continúa`.
2. **Un commit por acción**, con prefijo convencional y descripción en español, usando el mensaje de las tablas.
3. **Git solo en local:** prohibido `git pull`, `git fetch`, `git merge`, `git rebase`, `git push`, cambiar de rama y abrir el PR. Sí puede usar `git diff` y `git log` contra `feature/telemetry-frontend-capture` (ya está en local).
4. Prohibido `git add .` y `git add -A`: añadir rutas explícitas y ejecutar `git status` a solas antes de cada commit. El JSON local de TinyDB de proveedores está excluido por política: nunca escribir su ruta en comandos; si aparece en `git status`, parar y avisar.
5. **No puede leer ni editar ningún `.env*`** (política de la organización). Si hace falta comprobar algo de un `.env`, prepara el comando para Marisin.
6. **Ficheros autorizados:** solo los de la §3. **El frontend no se toca: ni una línea en `uis/`.** Tampoco `services/api/telemetry_schemas.py` (el modelo `TelemetryEvent` se reutiliza tal cual), manifiestos (`pyproject.toml`, `uv.lock`, `package*.json`), `infra/` ni credenciales.
7. **No instalar dependencias.** Solo lo que ya hay: FastAPI, Pydantic v2, SQLModel/SQLAlchemy y psycopg2. **No** se usa la librería `jsonschema` (no está instalada).
8. **pytest y uvicorn los ejecuta Marisin.** Todo lo que pase en Supabase (SQL Editor, consultas, capturas) también. El agente prepara los comandos y las consultas exactas, para y espera la salida.
9. **Cero PII en logs:** nunca registrar `properties`, `tags`, el `input` de los errores de Pydantic ni valores de los eventos. Solo conteos, `event_type` e índices/códigos de error.
10. Si algo del código real contradice este plan, **no inventar**: parar y avisar en el resumen.

---

## 1. Lo que exige la rúbrica (resumen)

- Tabla `telemetry_events` en Supabase con **8 columnas** (`id`, `timestamp`, `service`, `event_type`, `level`, `value`, `message`, `tags`), **3 índices** (`timestamp`, `event_type`, GIN en `tags`) y **sin lógica de UPDATE/DELETE**.
- `POST /telemetry/events` (misma URL) hace **bulk insert** (una sola operación por lote) y devuelve `{ "received", "stored", "rejected" }`.
- **Validación por evento** con `TelemetryEvent.model_validate(raw)` en un `try/except ValidationError`: los inválidos se cuentan en `rejected` y el resto del lote se guarda. **Prohibido** tipar el body como `list[TelemetryEvent]` (eso devuelve 422 a todo el lote).
- `TelemetryEvent` **no se modifica**.
- **El frontend no cambia ni una línea.**
- Los eventos aparecen con `event_type`, `timestamp` y `tags` bien poblados, técnicos y de negocio; `tags` respeta los allowlists y las dimensiones del BRIEFING (`warehouse`, `client_id`, `country`…) documentadas en `telemetry-plan.md`.
- Evidencia para el PR: captura de la tabla con ≥5 filas reales (al menos un evento técnico y uno de negocio), JSON de respuesta de un lote mixto y confirmación explícita de que el frontend no cambió.

---

## 2. Decisiones ya tomadas (D31–D42)

Se documentan en `telemetry-plan.md` (acción 1.4) para que contrato y código digan lo mismo.

| # | Decisión | Por qué |
|---|---|---|
| D31 | **Rama desde `feature/telemetry-frontend-capture`.** | El PR 2 no está mergeado y el stub, `TelemetryEvent` y el `TelemetryService` viven ahí. |
| D32 | **DDL versionado en `services/api/sql/001_telemetry_events.sql`**, que Marisin ejecuta en el SQL Editor de Supabase. La tabla **no** se declara como `SQLModel(table=True)`: el backend usa una `sqlalchemy.Table` en un `MetaData()` propio, fuera de `SQLModel.metadata`. | `create_all()` del arranque crearía una tabla sin el índice GIN, sin el trigger y sin RLS si la tabla aún no existiera. Con un `MetaData` propio, el arranque no la toca y la fuente de verdad del esquema es el `.sql`. Va dentro de `services/` porque el contenedor de la API solo monta esa carpeta. |
| D33 | **Inmutabilidad en la propia BD**, no solo "no programar UPDATE": trigger `BEFORE UPDATE OR DELETE` (por fila) y `BEFORE TRUNCATE` (por sentencia) que lanzan excepción; RLS activada **sin políticas**; `REVOKE UPDATE, DELETE, TRUNCATE` a `anon` y `authenticated`. | Un evento es un hecho inmutable. RLS sin políticas cierra la tabla a la API REST pública de Supabase; el backend conecta como propietario por el pooler, así que puede insertar. |
| D34 | **Catálogo en Python:** `services/api/telemetry_catalog.py` con, por cada uno de los 20 `event_type`: `level` (`x-level`), `value_property` (`x-value-property` o `None`), `allowed_properties` (claves del allowlist) y `summary` (la `description` del esquema). Un test comprueba la **paridad exacta** con `docs/telemetry/event-schemas.json`. | El contenedor de la API no monta `docs/`, así que leer el JSON en runtime rompería en Docker. El test de paridad impide que el catálogo y el contrato se separen. |
| D35 | **Envelope laxo + validación por evento.** Body: `TelemetryIngestEnvelope(events: list[Any] = Field(max_length=50))`. Cada item → `TelemetryEvent.model_validate(raw)`; además se **rechaza** si su `event_type` no está en el catálogo. Un item que no es objeto también se rechaza. | Cumple la validación parcial. El límite de 50 se mantiene a nivel de envelope (D27): un lote de más de 50 sigue dando 422, igual que con el stub; el frontend nunca lo supera (`BATCH_SIZE`). |
| D36 | **`tags` plano** = `properties` filtradas al allowlist del evento **+** `eventId`, `sessionId`, `userId`, `schemaVersion` y `requestId` (como ya fija §11). Las claves fuera del allowlist se **descartan** (no rechazan el evento); el log solo cuenta cuántas. Se construye desde `event.model_dump(mode="json", by_alias=True)` para que los UUID y fechas lleguen como texto. | Plano permite consultas por contención (`tags @> '{"warehouse":"zaragoza"}'`) que aprovecha el GIN. `TelemetryEvent` acepta `properties: dict[str, Any]` y no se puede tocar, así que el allowlist se aplica al mapear: nunca entra en la BD una clave no autorizada. |
| D37 | **Mapeo de columnas:** `service = "backoffice"` (constante; D21); `level = x-level`; `value = properties[value_property]` solo si es `int`/`float` y no `bool`, si no `NULL` (nunca 0); `message = summary` del catálogo (texto fijo, sin datos del evento); `timestamp = event.timestamp`. | Es el mapeo de §11 llevado a código. El mensaje fijo evita meter PII o texto libre en una columna legible. |
| D38 | **Bulk insert real:** un único `INSERT … VALUES (…), (…), …` con `session.execute(insert(telemetry_events).values(rows))` y un `commit()`. Si no hay eventos válidos, **no se toca la BD**. | Una sola sentencia y una sola transacción por lote (no `executemany`, que en psycopg2 son N sentencias). |
| D39 | **Fallo de BD → `rollback()` y `503`** (`detail`: "Telemetry storage unavailable"). | La transacción es todo-o-nada: el `TelemetryService` reintenta el lote entero ante un no-2xx (`response.ok`) sin crear duplicados parciales. Un `200` con `rejected > 0` **no** provoca reintentos, que es lo correcto: un evento inválido no se arregla reenviándolo. |
| D40 | **Deduplicación por `eventId` en la consulta, no en la ingesta** (como ya dice §10). Sin índice único. Se documenta la consulta con `DISTINCT ON (tags->>'eventId')`. | El reintento y el flush por `sendBeacon` pueden reenviar un lote. Mantener los tres índices de la rúbrica y la regla ya aprobada en §10. |
| D41 | **Logs sin datos:** una línea por lote con `received`, `stored`, `rejected` y los `event_type` válidos; por cada rechazo, el índice y los códigos `type`/`loc` de Pydantic obtenidos con `exc.errors(include_input=False, include_url=False, include_context=False)`. | Diagnóstico sin exponer `properties` ni valores. Se conserva la garantía del test actual (`TELEMETRY_PROPERTY_MUST_NOT_BE_LOGGED`). |
| D42 | **Respuesta:** `TelemetryIngestResult(received, stored, rejected)` como `response_model`, siempre `200` si el envelope es válido. `received = len(events)`, `stored + rejected = received`. | Es el contrato de la rúbrica y mantiene el `response_model` que exige `test_serialization_contracts.py`. |

**Esbozo de referencia** (el agente lo adapta, no improvisa otra arquitectura):

```python
# services/api/routes/telemetry.py
@router.post("/events", response_model=TelemetryIngestResult)
def receive_telemetry_events(
    envelope: TelemetryIngestEnvelope,
    session: Annotated[Session, Depends(get_db)],
) -> TelemetryIngestResult:
    rows, rejected = prepare_rows(envelope.events)   # model_validate por item + catálogo + mapeo
    stored = 0
    if rows:
        try:
            stored = bulk_insert_events(session, rows)  # 1 INSERT ... VALUES multi-fila + commit
        except SQLAlchemyError:
            session.rollback()
            raise HTTPException(status_code=503, detail="Telemetry storage unavailable")
    return TelemetryIngestResult(received=len(envelope.events), stored=stored, rejected=rejected)
```

---

## 3. Hallazgos del código (confirmar en la Fase 0)

| # | Hallazgo | Dónde |
|---|---|---|
| H1 | El stub tipa el body como `batch: TelemetryBatch` (`events: list[TelemetryEvent]`): un evento inválido → 422 para todo el lote. Es justo lo que hay que sustituir. | `services/api/routes/telemetry.py` |
| H2 | `TelemetryEvent`: `extra="forbid"`, `timestamp: AwareDatetime` (un timestamp sin zona se rechaza), `event_type` con patrón, `userId` nullable, `properties: dict[str, Any]`. | `services/api/telemetry_schemas.py` |
| H3 | El `TelemetryService` solo mira `response.ok`: reintenta 3 veces ante no-2xx e ignora el body. | `uis/backoffice/src/lib/telemetry.ts` (~L430–445) |
| H4 | El contenedor `api` monta solo `./services` → `docs/` no existe en runtime. | `docker-compose.yml` |
| H5 | `get_db()` usa `DATABASE_URL` (pooler de Supabase, `NullPool`, `sslmode=require`); el arranque solo hace `SQLModel.metadata.create_all(engine)`. | `services/api/database.py`, `main.py` |
| H6 | `event-schemas.json`: 20 eventos en `definitions`; el allowlist está en `allOf[1].properties.properties.properties`; `x-level` y `x-value-property` por evento (p. ej. `api_request_failed` → `error` / `status_code`; `page_viewed` → `info` / `None`). | `docs/telemetry/event-schemas.json` |
| H7 | `test_serialization_contracts.py` cuenta **32 rutas** y exige `response_model`. La ruta es la misma, así que el conteo **no cambia**. | `tests/` |
| H8 | `tests/test_telemetry_stub.py` tiene 5 tests que asumen el stub (`{"received": N}` y 422 por evento inválido). Hay que reescribirlos. | `tests/` |
| H9 | `telemetry-plan.md` §11 dice que el mapeo es "conceptual; no define una tabla". Hay que actualizarlo. | `docs/telemetry/` |
| H10 | Línea base esperada: `pytest -q` → **42 passed**. | `memory-bank/progress.md` |

---

## 4. Ficheros autorizados

**Nuevos**
- `services/api/sql/001_telemetry_events.sql` — DDL, índices, trigger, RLS y revokes.
- `services/api/telemetry_catalog.py` — catálogo de D34.
- `services/api/telemetry_storage.py` — `Table` de SQLAlchemy (MetaData propio) y `bulk_insert_events()`.
- `services/api/telemetry_ingest.py` — `TelemetryIngestEnvelope`, `TelemetryIngestResult` y `prepare_rows()` (validación por evento + mapeo a fila).
- `tests/test_telemetry_catalog.py`, `tests/test_telemetry_storage.py`.
- `docs/telemetry/storage-verification.md` y `docs/telemetry/evidence/` (lote mixto, respuesta y capturas).

**Modificar**
- `services/api/routes/telemetry.py` — sustituir el stub.
- `tests/test_telemetry_stub.py` → **`git mv`** a `tests/test_telemetry_events.py` y reescribir.
- `docs/telemetry/telemetry-plan.md` (§11, D31–D42 y riesgos), `memory-bank/progress.md`, `prompts/README.md`, `prompts/telemetry-storage/`.

**Prohibido tocar:** `uis/` entero, `services/api/telemetry_schemas.py`, `services/api/main.py` (el router ya está registrado), `docs/telemetry/event-schemas.json`, cualquier `.env*`.

---

## 5. Fase 0 — Reconocimiento y línea base

| # | Acción | Commit |
|---|---|---|
| 0.1 | Commitear este plan y el prompt. | `docs: añadir plan por fases y prompt del almacenamiento de telemetría` |
| 0.2 | Añadir la fila del proyecto en `prompts/README.md` (y marcar "Captura de telemetría en el frontend" como "PR abierto"). | `docs: registrar el proyecto de almacenamiento de telemetría en el índice de prompts` |
| 0.3 | Leer `AGENTS.md`, `memory-bank/projectbrief.md`, `techContext.md`, `progress.md`, `CONTEXT.md` y `docs/telemetry/telemetry-plan.md` (§4, §10, §11 y D21–D30). | — |
| 0.4 | Confirmar H1–H9 en el código y anotar cualquier diferencia. | — |
| 0.5 | Preparar para Marisin: `python -m pytest -q` (esperado 42 passed) y la comprobación de que existe `DATABASE_URL` **sin mostrar su valor**: `grep -c '^DATABASE_URL=' .env` (esperado `1`). | — |
| 0.6 | `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 0 de almacenamiento` |

🛑 **STOP — auditoría de Fase 0.**

---

## 6. Fase 1 — Tabla `telemetry_events` en Supabase

| # | Acción | Commit |
|---|---|---|
| 1.1 | Crear `services/api/sql/001_telemetry_events.sql`, idempotente (`if not exists` / `create or replace` / `drop trigger if exists`), con: tabla `public.telemetry_events` con las 8 columnas de la rúbrica (`id uuid primary key default gen_random_uuid()`, `"timestamp" timestamptz not null`, `service text not null`, `event_type text not null`, `level text not null default 'info'` con `check (level in ('info','warn','error'))`, `value numeric`, `message text`, `tags jsonb not null default '{}'::jsonb`); `comment on table` explicando que es solo escritura; los 3 índices `telemetry_events_timestamp_idx` (`"timestamp" desc`), `telemetry_events_event_type_idx` y `telemetry_events_tags_gin_idx` (`using gin (tags)`); la función `telemetry_events_block_mutation()` y los triggers `telemetry_events_no_update_delete` (before update or delete, for each row) y `telemetry_events_no_truncate` (before truncate, for each statement); `alter table … enable row level security` sin políticas; `revoke update, delete, truncate … from anon, authenticated`. Sin `DROP TABLE`. | `feat: añadir el DDL de la tabla telemetry_events con índices e inmutabilidad` |
| 1.2 | **Marisin** ejecuta el `.sql` completo en Supabase → SQL Editor. El agente le prepara estas consultas de verificación y espera la salida: columnas (`select column_name, data_type, is_nullable, column_default from information_schema.columns where table_name = 'telemetry_events' order by ordinal_position;`), índices (`select indexname, indexdef from pg_indexes where tablename = 'telemetry_events';`), triggers (`select tgname from pg_trigger where tgrelid = 'public.telemetry_events'::regclass and not tgisinternal;`) y RLS (`select relrowsecurity from pg_class where oid = 'public.telemetry_events'::regclass;`). Capturas → `docs/telemetry/evidence/supabase-table-structure.png` y `supabase-indexes.png` (las sube Marisin; comprobar que caen en esa carpeta). | `docs: añadir evidencia de la estructura de telemetry_events en Supabase` |
| 1.3 | Crear `docs/telemetry/storage-verification.md` con: cómo aplicar el DDL, las 4 consultas de 1.2 con sus resultados, y las consultas de ejemplo para el análisis: últimos eventos (`order by "timestamp" desc limit 20`), conteo por `event_type`, filtro por dimensión (`where tags @> '{"warehouse":"zaragoza"}'`) y deduplicación por `eventId` (D40, `select distinct on (tags->>'eventId') …`). | `docs: añadir la guía de verificación del almacenamiento de telemetría` |
| 1.4 | `telemetry-plan.md`: reescribir §11 como **mapeo implementado** (tabla real, columna ← origen, D36/D37, ejemplo de fila para `outbound_order_created`), añadir D31–D42 en §2.2 (subapartado "Decisiones de implementación (almacenamiento)") y en §10 sustituir "deduplicar antes de agregar" por la referencia a la consulta de D40. Actualizar el Índice si cambia algún título. | `docs: documentar en el plan de telemetría el almacenamiento y el mapeo a tags` |
| 1.5 | `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 1 de almacenamiento` |

**Criterio de aceptación:** la tabla existe con 8 columnas, 3 índices propios (+ la PK), 2 triggers y RLS activa; el `.sql` vuelve a ejecutarse sin error (idempotente).

🛑 **STOP — auditoría de Fase 1** (con las salidas de las 4 consultas).

---

## 7. Fase 2 — Endpoint real en FastAPI

| # | Acción | Commit |
|---|---|---|
| 2.1 | `services/api/telemetry_catalog.py`: `@dataclass(frozen=True) EventContract(level, value_property, allowed_properties: frozenset[str], summary)` y `EVENT_CATALOG: dict[str, EventContract]` con los **20** eventos, copiados de `event-schemas.json` (D34). Constante `TELEMETRY_SERVICE = "backoffice"`. | `feat: añadir el catálogo de contratos de telemetría para el almacenamiento` |
| 2.2 | `tests/test_telemetry_catalog.py`: carga `docs/telemetry/event-schemas.json` y comprueba, para todos los eventos, que coinciden el conjunto de `event_type`, `level`, `value_property`, `allowed_properties` y `summary`. | `test: comprobar la paridad del catálogo con event-schemas.json` |
| 2.3 | `services/api/telemetry_storage.py`: `telemetry_metadata = MetaData()` (no `SQLModel.metadata`), `telemetry_events = Table(...)` con las 8 columnas (`JSONB` de `sqlalchemy.dialects.postgresql`, `server_default` para `id`, `level` y `tags`) y `bulk_insert_events(session, rows) -> int` que ejecuta **un** `insert(telemetry_events).values(rows)`, hace `commit()` y devuelve `len(rows)` (D38). Sin funciones de update ni delete. | `feat: añadir el bulk insert de eventos en telemetry_events` |
| 2.4 | `tests/test_telemetry_storage.py`: compilar `insert(telemetry_events).values(rows)` con 3 filas para el dialecto `postgresql` y comprobar que es **una** sentencia `INSERT` con 3 grupos de `VALUES`; y que `bulk_insert_events` llama a `execute` una sola vez y a `commit` una vez (sesión falsa). Comprobar que `telemetry_events` no está en `SQLModel.metadata.tables`. | `test: cubrir el insert multi-fila de telemetría` |
| 2.5 | `services/api/telemetry_ingest.py`: `TelemetryIngestEnvelope` (D35), `TelemetryIngestResult` (D42) y `prepare_rows(raw_events) -> tuple[list[dict], int, list[dict]]` que, por item: `TelemetryEvent.model_validate(raw)` dentro de `try/except ValidationError`; rechaza si `event_type` no está en `EVENT_CATALOG`; mapea a fila según D36/D37. Devuelve filas, nº de rechazados y el diagnóstico sin valores de D41. **Importa `TelemetryEvent` de `telemetry_schemas.py` sin tocar ese fichero.** | `feat: validar cada evento de telemetría y mapearlo a una fila` |
| 2.6 | `services/api/routes/telemetry.py`: sustituir el stub según el esbozo de la §2 (misma ruta y prefijo, sin JWT, `Depends(get_db)`, 503 de D39, log de D41). Conservar `TELEMETRY_ENDPOINT`. Quitar el import de `TelemetryBatch`/`TelemetryReceived` (los modelos se quedan en `telemetry_schemas.py` sin uso, para no modificar ese fichero). | `feat: sustituir el stub de telemetría por el endpoint real con bulk insert` |
| 2.7 | `git mv tests/test_telemetry_stub.py tests/test_telemetry_events.py` y reescribirlo con `app.dependency_overrides[get_db]` y `monkeypatch` de `bulk_insert_events` para capturar las filas. Casos: lote válido de 2 (negocio + técnico) → `200 {2,2,0}` y **una** llamada al insert; lote mixto (6 items de la Fase 3) → `{6,2,4}`; lote vacío → `{0,0,0}` sin llamar al insert; todos inválidos → sin llamar al insert; `event_type` fuera del catálogo → rechazado; clave fuera del allowlist → no aparece en `tags`; `tags` contiene `eventId`/`sessionId`/`userId`/`schemaVersion`/`requestId`; `level` y `value` según el catálogo (`value` `None` en `page_viewed`); >50 eventos → 422; body sin `events` → 422; fallo `SQLAlchemyError` → 503 y `rollback`; y el log no contiene `TELEMETRY_PROPERTY_MUST_NOT_BE_LOGGED`. | `test: cubrir la validación parcial y el almacenamiento del endpoint de telemetría` |
| 2.8 | Preparar para Marisin: `python -m pytest -q` (esperado: 42 − 5 + los nuevos, todo verde) y el arranque `python -m uvicorn services.api.main:app --port 8000` comprobando `GET /docs` → 200. Preparar también las dos comprobaciones de alcance: `git diff --stat feature/telemetry-frontend-capture -- uis/ services/api/telemetry_schemas.py services/api/main.py` (esperado: **vacío**). | — |
| 2.9 | `progress.md`. | `docs: actualizar progress.md con el cierre de la fase 2 de almacenamiento` |

**Criterio de aceptación:** pytest en verde; la ruta sigue siendo `POST /telemetry/events` con `response_model`; el conteo de 32 rutas no cambia; el diff de `uis/`, `telemetry_schemas.py` y `main.py` está vacío.

🛑 **STOP — auditoría de Fase 2.**

---

## 8. Fase 3 — Verificación end-to-end y cierre

| # | Acción | Commit |
|---|---|---|
| 3.1 | Crear `docs/telemetry/evidence/mixed-batch.json` con 6 items, todos con `userId: "curl_verification"` para poder filtrarlos: **(1)** `inbound_order_created` válido (propiedades del `examples` del esquema) **más** una clave extra `"unexpected_key": "x"`; **(2)** `api_request_failed` válido (`api_endpoint: "/inventory/orders/outbound"`, `failure_reason: "http_5xx"`, `status_code: 503`); **(3)** sin `eventId`; **(4)** `timestamp` sin zona horaria (`"2026-11-18T12:00:00"`); **(5)** `event_type: "inventory_teleported"` (fuera del catálogo); **(6)** el string `"no-soy-un-objeto"`. UUID nuevos en cada evento. | `test: añadir el lote mixto de verificación del almacenamiento` |
| 3.2 | **Marisin:** con la API arrancada, `curl -s -X POST http://localhost:8000/telemetry/events -H 'Content-Type: application/json' -d @docs/telemetry/evidence/mixed-batch.json` → esperado `{"received":6,"stored":2,"rejected":4}`. Guardar la respuesta en `docs/telemetry/evidence/mixed-batch-response.json` y pegar la línea del log de la API. En Supabase: `select event_type, level, value, tags from public.telemetry_events where tags->>'userId' = 'curl_verification';` → 2 filas y **sin** `unexpected_key`. | `docs: añadir la respuesta del lote mixto con stored y rejected` |
| 3.3 | **Marisin, en el backoffice** (API + `npm run dev`): login fallido y correcto; una **orden de entrada** y una **de salida**; navegar por varias secciones; esperar ≥10 s (o cambiar de pestaña para forzar el flush). Consulta: `select "timestamp", service, event_type, level, value, message, tags from public.telemetry_events where tags->>'userId' is distinct from 'curl_verification' order by "timestamp" desc limit 20;`. Comprobar `inbound_order_created`, `outbound_order_created`, `user_login_failed`, `page_viewed`… con `warehouse`, `client_id` y `country` en `tags`. Captura con ≥5 filas (al menos una técnica y una de negocio) → `docs/telemetry/evidence/supabase-telemetry-rows.png`. | `docs: añadir evidencia de eventos reales guardados en Supabase` |
| 3.4 | **Marisin, inmutabilidad:** `update public.telemetry_events set level = 'error' where id = (select id from public.telemetry_events limit 1);` y `delete from public.telemetry_events where id = (select id from public.telemetry_events limit 1);` → ambos deben **fallar** con el mensaje del trigger. Añadir el resultado a `storage-verification.md`. | `docs: registrar la prueba de inmutabilidad de telemetry_events` |
| 3.5 | Comprobaciones finales (el agente ejecuta las de git, Marisin pytest): `git diff --stat feature/telemetry-frontend-capture -- uis/ services/api/telemetry_schemas.py` → vacío; `git log --oneline feature/telemetry-frontend-capture..HEAD`; `python -m pytest -q` en verde. | — |
| 3.6 | `progress.md`, marcar el proyecto en `prompts/README.md` como "PR abierto" y redactar en el resumen (no en un fichero) la descripción del PR: capturas, JSON del lote mixto, confirmación explícita de que el frontend no cambió (con la salida vacía del `git diff`), y la lista de decisiones D31–D42. | `docs: actualizar progress.md con el cierre del almacenamiento de telemetría` |

🛑 **STOP final.** Marisin sube la rama y abre el PR `feat: telemetry event storage` cuando Claude dé el OK.

---

## 9. Plantilla de resumen al cerrar cada fase

```
## Resumen Fase N — <nombre>
**Commits realizados:** (hash corto + mensaje, en orden)
**Ficheros tocados:**
**Qué se hizo:** (3–6 viñetas)
**Decisiones tomadas por el agente que no estaban en el plan:**
**Discrepancias con el código real o con el plan de telemetría:**
**Comandos / consultas que debe ejecutar Marisin:** (exactos, en orden)
**Checklist de rúbrica cubierto en esta fase:**
⏸ Esperando "OK fase N, continúa".
```

---

## 10. Checklist de la rúbrica (auditoría final)

- [ ] `telemetry_events` existe en Supabase con las 8 columnas, los 3 índices (`timestamp`, `event_type`, GIN en `tags`) y sin UPDATE/DELETE (trigger + RLS + revoke, y ningún código que lo haga).
- [ ] `POST /telemetry/events` hace **un** `INSERT` multi-fila por lote y devuelve `{received, stored, rejected}`.
- [ ] Validación por evento con `TelemetryEvent.model_validate` en un bucle; el body no está tipado como `list[TelemetryEvent]`; un lote mixto da 200 y guarda los válidos.
- [ ] `services/api/telemetry_schemas.py` sin cambios (`git diff` vacío).
- [ ] `uis/` sin cambios (`git diff` vacío) y `NEXT_PUBLIC_TELEMETRY_ENDPOINT` sigue igual.
- [ ] Eventos reales técnicos y de negocio en la tabla con `event_type`, `timestamp` y `tags` correctos.
- [ ] `tags` solo contiene claves del allowlist + los 5 campos del envelope de §11, con `warehouse`, `client_id` y `country` en los eventos de inventario.
- [ ] `telemetry-plan.md` §11 documenta el mapeo real y D31–D42.
- [ ] pytest en verde, sin datos de eventos en los logs.
- [ ] PR `feat: telemetry event storage` con captura de ≥5 filas, JSON del lote mixto y confirmación de que el frontend no cambió.
