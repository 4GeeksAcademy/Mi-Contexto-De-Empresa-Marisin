# Verificación del almacenamiento de telemetría

Guía del proyecto *Telemetría 3/3 – Almacenamiento*: cómo crear la tabla `telemetry_events` en Supabase, cómo comprobar su estructura y cómo consultar los eventos guardados. Las decisiones D31–D42 están en `docs/telemetry/telemetry-plan.md` (§2.2) y el mapeo de columnas en su §11.

## 1. Crear la tabla

1. Abrir el proyecto de Supabase → **SQL Editor** → **New query**.
2. Pegar el contenido completo de `services/api/sql/001_telemetry_events.sql` y pulsar **Run**.
3. El script es idempotente: si se vuelve a ejecutar, no falla ni borra datos.

El backend **no** crea esta tabla al arrancar (D32): `create_all()` solo conoce `SQLModel.metadata`, y la tabla de telemetría se declara en un `MetaData` propio en `services/api/telemetry_storage.py`.

## 2. Comprobar la estructura

Ejecutar cada consulta en el SQL Editor.

**Columnas** (esperado: 8, en este orden):

```sql
select column_name, data_type, is_nullable, column_default
from information_schema.columns
where table_schema = 'public' and table_name = 'telemetry_events'
order by ordinal_position;
```

| Columna | Tipo | Nulable | Default |
|---|---|---|---|
| `id` | `uuid` | NO | `gen_random_uuid()` |
| `timestamp` | `timestamp with time zone` | NO | — |
| `service` | `text` | NO | — |
| `event_type` | `text` | NO | — |
| `level` | `text` | NO | `'info'::text` |
| `value` | `numeric` | YES | — |
| `message` | `text` | YES | — |
| `tags` | `jsonb` | NO | `'{}'::jsonb` |

**Índices** (esperado: la PK y los tres de la rúbrica):

```sql
select indexname, indexdef
from pg_indexes
where schemaname = 'public' and tablename = 'telemetry_events';
```

Resultado esperado: `telemetry_events_pkey`, `telemetry_events_timestamp_idx`, `telemetry_events_event_type_idx` y `telemetry_events_tags_gin_idx` (`USING gin (tags)`).

**Triggers de inmutabilidad** (esperado: 2):

```sql
select tgname
from pg_trigger
where tgrelid = 'public.telemetry_events'::regclass and not tgisinternal;
```

Resultado esperado: `telemetry_events_no_update_delete` y `telemetry_events_no_truncate`.

**RLS activa** (esperado: `true`):

```sql
select relrowsecurity
from pg_class
where oid = 'public.telemetry_events'::regclass;
```

Evidencias: `docs/telemetry/evidence/supabase-table-structure.png` y `docs/telemetry/evidence/supabase-indexes.png`.

## 3. Inmutabilidad

La tabla es de solo escritura (D33). Con al menos una fila guardada, estas dos sentencias deben **fallar** con `telemetry_events es de solo escritura: UPDATE no está permitido` (o `DELETE`):

```sql
update public.telemetry_events set level = 'error'
where id = (select id from public.telemetry_events limit 1);

delete from public.telemetry_events
where id = (select id from public.telemetry_events limit 1);
```

Un `UPDATE` o `DELETE` que no afecta a ninguna fila no dispara el trigger, por eso la prueba se hace sobre una fila real.

## 4. Consultas de análisis

**Últimos eventos:**

```sql
select "timestamp", service, event_type, level, value, message, tags
from public.telemetry_events
order by "timestamp" desc
limit 20;
```

**Volumen por tipo de evento:**

```sql
select event_type, level, count(*) as total
from public.telemetry_events
group by event_type, level
order by total desc;
```

**Filtro por dimensión del BRIEFING** (usa el índice GIN):

```sql
select event_type, tags->>'client_id' as client_id, value as quantity, "timestamp"
from public.telemetry_events
where tags @> '{"warehouse": "zaragoza"}'
order by "timestamp" desc;
```

**Deduplicación por `eventId`** (D40): un reintento o el flush por `sendBeacon` pueden reenviar un lote. Antes de agregar, quedarse con una fila por `eventId`:

```sql
with deduplicated as (
  select distinct on (tags->>'eventId') *
  from public.telemetry_events
  order by tags->>'eventId', "timestamp"
)
select event_type, count(*) as total
from deduplicated
group by event_type
order by total desc;
```

Las filas de la verificación manual con curl llevan `tags->>'userId' = 'curl_verification'`; excluirlas de los análisis con `where tags->>'userId' is distinct from 'curl_verification'`.

## 5. Resultados de la verificación

Verificación realizada el 2026-11-19 sobre el proyecto de Supabase `trackflow-inventory-hito5-db`.

**Estructura (§2).** La consulta combinada de columnas, índices, triggers y RLS devolvió 15 filas: las 8 columnas con los tipos y defaults de la tabla de §2, los índices `telemetry_events_pkey`, `telemetry_events_timestamp_idx`, `telemetry_events_event_type_idx` y `telemetry_events_tags_gin_idx`, los triggers `telemetry_events_no_update_delete` y `telemetry_events_no_truncate`, y `relrowsecurity = true`. Evidencia: `evidence/supabase-table-structure.png`.

**Lote mixto.** `curl -s -X POST http://localhost:8000/telemetry/events -H 'Content-Type: application/json' -d @docs/telemetry/evidence/mixed-batch.json` respondió `200` con:

```json
{"received":6,"stored":2,"rejected":4}
```

El log de la API registró solo conteos y códigos de error, sin datos de los eventos:

```text
Telemetry batch: received=6 stored=2 rejected=4 dropped_property_keys=1 types=['inbound_order_created', 'api_request_failed']
Telemetry rejected events: [{'index': 2, 'errors': [{'type': 'missing', 'loc': ['eventId']}]}, {'index': 3, 'errors': [{'type': 'timezone_aware', 'loc': ['timestamp']}]}, {'index': 4, 'errors': [{'type': 'unknown_event_type', 'loc': ['event_type']}]}, {'index': 5, 'errors': [{'type': 'model_type', 'loc': []}]}]
```

En Supabase aparecen las 2 filas válidas (`inbound_order_created` con `level = info`, `value = 12`; `api_request_failed` con `level = error`, `value = 503`), y `tags ? 'unexpected_key'` es `false` en ambas: la clave fuera del allowlist se descartó. Evidencia: `evidence/mixed-batch.json` y `evidence/mixed-batch-response.json`.

**Eventos reales del backoffice.** Con la API y el backoffice en marcha (login fallido y correcto, navegación, una orden de entrada y una de salida), la API registró lotes con `rejected=0` y la tabla quedó así:

| `event_type` | `level` | Total |
|---|---|---|
| `api_latency_recorded` | `info` | 23 |
| `page_viewed` | `info` | 13 |
| `web_vital_recorded` | `info` | 4 |
| `inbound_order_created` | `info` | 2 |
| `api_request_failed` | `error` | 1 |
| `user_login_failed` | `warn` | 1 |
| `user_login_succeeded` | `info` | 1 |
| `outbound_order_created` | `info` | 1 |

Los totales incluyen las 2 filas del lote mixto (`userId = curl_verification`). Los eventos de inventario guardan en `tags` las dimensiones del BRIEFING (`warehouse = los_angeles`, `client_id = ecowear_usa`, `country = US`), los técnicos guardan su medida en `value` (ms de latencia) y `page_viewed` deja `value` en `NULL`. Evidencia: `evidence/supabase-telemetry-rows.png`.

**Inmutabilidad (§3).** Sobre una fila real, las dos sentencias fallaron:

```text
ERROR: 42501: telemetry_events es de solo escritura: UPDATE no está permitido
ERROR: 42501: telemetry_events es de solo escritura: DELETE no está permitido
CONTEXT: PL/pgSQL function telemetry_events_block_mutation() line 3 at RAISE
```

**Frontend sin cambios.** `git diff --stat origin/main -- uis/ services/api/telemetry_schemas.py` no devuelve nada: el `TelemetryService` y el modelo `TelemetryEvent` son los del proyecto anterior.
