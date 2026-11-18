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

_Se completa en las fases 1 y 3 del plan con las salidas reales de Supabase, la respuesta del lote mixto y la prueba de inmutabilidad._
