-- TrackFlow · Telemetría 3/3 · Tabla de almacenamiento de eventos.
--
-- Se ejecuta a mano en Supabase (SQL Editor). Es idempotente: puede
-- ejecutarse varias veces sin error y nunca borra datos.
--
-- La tabla es de solo escritura (D33): los eventos son hechos inmutables.
-- No existe lógica de UPDATE ni DELETE en el backend, y la propia base de
-- datos los bloquea con triggers. RLS sin políticas cierra la tabla a la API
-- REST pública de Supabase; el backend inserta como propietario a través del
-- pooler de DATABASE_URL.

-- gen_random_uuid() es nativo desde PostgreSQL 13: no hace falta ninguna extensión.

create table if not exists public.telemetry_events (
  id          uuid        primary key default gen_random_uuid(),
  "timestamp" timestamptz not null,
  service     text        not null,
  event_type  text        not null,
  level       text        not null default 'info'
                          check (level in ('info', 'warn', 'error')),
  value       numeric,
  message     text,
  tags        jsonb       not null default '{}'::jsonb
);

comment on table public.telemetry_events is
  'Eventos de telemetría de TrackFlow. Solo escritura: los eventos son inmutables (sin UPDATE, DELETE ni TRUNCATE).';
comment on column public.telemetry_events."timestamp" is
  'Hora de captura del evento en el cliente (UTC), no hora de recepción.';
comment on column public.telemetry_events.service is
  'Origen del evento; hoy siempre backoffice (D21).';
comment on column public.telemetry_events.level is
  'Severidad del contrato del evento (x-level de event-schemas.json).';
comment on column public.telemetry_events.value is
  'Valor numérico de la propiedad x-value-property del evento; NULL si no aplica.';
comment on column public.telemetry_events.message is
  'Resumen legible fijo del tipo de evento; nunca contiene datos del evento.';
comment on column public.telemetry_events.tags is
  'properties filtradas al allowlist del evento + eventId, sessionId, userId, schemaVersion y requestId.';

-- Índices para las consultas analíticas.
create index if not exists telemetry_events_timestamp_idx
  on public.telemetry_events ("timestamp" desc);

create index if not exists telemetry_events_event_type_idx
  on public.telemetry_events (event_type);

create index if not exists telemetry_events_tags_gin_idx
  on public.telemetry_events using gin (tags);

-- Inmutabilidad: cualquier UPDATE, DELETE o TRUNCATE falla.
create or replace function public.telemetry_events_block_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'telemetry_events es de solo escritura: % no está permitido', tg_op
    using errcode = 'insufficient_privilege';
end;
$$;

drop trigger if exists telemetry_events_no_update_delete on public.telemetry_events;
create trigger telemetry_events_no_update_delete
  before update or delete on public.telemetry_events
  for each row execute function public.telemetry_events_block_mutation();

drop trigger if exists telemetry_events_no_truncate on public.telemetry_events;
create trigger telemetry_events_no_truncate
  before truncate on public.telemetry_events
  for each statement execute function public.telemetry_events_block_mutation();

-- Sin acceso desde la API REST pública de Supabase.
alter table public.telemetry_events enable row level security;

revoke update, delete, truncate on public.telemetry_events from anon, authenticated;
