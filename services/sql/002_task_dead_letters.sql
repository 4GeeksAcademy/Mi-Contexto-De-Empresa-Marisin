-- TrackFlow · Colas de mensajes y tareas asíncronas (Ticket #DEV-55) · Dead Letter Queue.
--
-- Se ejecuta a mano en Supabase (SQL Editor). Es idempotente: puede ejecutarse
-- varias veces sin error y nunca borra datos.
--
-- Una fila por tarea de Celery que agotó sus reintentos (max_retries = 3, es decir,
-- 4 intentos). La escribe el worker al consumir la cola `dead_letter`
-- (`services/tasks.py` → `services/dead_letter.py`), nunca la API.
--
-- `task_id` es único: si el mensaje de la DLQ se reentrega, no se duplica la fila.
-- `task_kwargs` guarda solo las referencias que llevaba el mensaje (week_start,
-- triggered_by), nunca datos voluminosos.
--
-- RLS sin políticas cierra la tabla a la API REST pública de Supabase; el worker
-- escribe como propietario a través del pooler de DATABASE_URL.

create table if not exists public.task_dead_letters (
  id            uuid        primary key default gen_random_uuid(),
  task_id       text        not null,
  task_name     text        not null,
  attempt       integer     not null check (attempt >= 1),
  max_retries   integer     not null check (max_retries >= 0),
  error_type    text        not null,
  error_message text        not null,
  task_kwargs   jsonb       not null default '{}'::jsonb,
  failed_at     timestamptz not null,
  recorded_at   timestamptz not null default now()
);

comment on table public.task_dead_letters is
  'Dead Letter Queue: tareas de Celery que fallaron tras agotar sus reintentos.';
comment on column public.task_dead_letters.task_id is
  'Id de la tarea en Celery (el mismo que devuelve la API con 202 y consulta GET /tasks/{task_id}).';
comment on column public.task_dead_letters.attempt is
  'Número del intento que falló por última vez (1 + reintentos ejecutados).';
comment on column public.task_dead_letters.error_message is
  'Mensaje completo del último error (truncado a 4000 caracteres).';
comment on column public.task_dead_letters.failed_at is
  'Momento del último fallo, en el worker.';

create unique index if not exists task_dead_letters_task_id_idx
  on public.task_dead_letters (task_id);

create index if not exists task_dead_letters_failed_at_idx
  on public.task_dead_letters (failed_at desc);

alter table public.task_dead_letters enable row level security;

-- Verificación (debe devolver las 10 columnas):
-- select column_name, data_type, is_nullable
-- from information_schema.columns
-- where table_schema = 'public' and table_name = 'task_dead_letters'
-- order by ordinal_position;
