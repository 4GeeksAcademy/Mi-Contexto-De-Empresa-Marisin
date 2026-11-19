-- TrackFlow · Procesos en segundo plano · Tabla de control de ejecuciones `job_runs`.
--
-- Se ejecuta a mano en Supabase (SQL Editor). Es idempotente: puede ejecutarse
-- varias veces sin error y nunca borra datos.
--
-- Una fila por ejecución del script nocturno (`scripts/nightly_export.py`) que
-- llega a crear su registro. Máquina de estados (J2 del plan):
--
--   pending → processing → completed
--                       ↘ failed
--
-- El lock distribuido ES el estado `processing` (J3): el índice único parcial
-- `job_runs_single_processing_idx` impide que haya dos filas `processing` del
-- mismo job, así que la transición pending → processing es atómica en la base
-- de datos y la segunda instancia la pierde. No hay tabla, columna ni flag de
-- lock aparte.
--
-- `job_runs` (orquestación nocturna) no sustituye a `reporting.pipeline_runs`
-- (fases internas del ETL): cada capa registra lo suyo (J1).
--
-- RLS sin políticas cierra la tabla a la API REST pública de Supabase; el script
-- escribe como propietario a través del pooler de DATABASE_URL.

create table if not exists public.job_runs (
  id            uuid        primary key default gen_random_uuid(),
  job_name      text        not null,
  target_date   date        not null,
  status        text        not null default 'pending'
                            check (status in ('pending', 'processing', 'completed', 'failed')),
  started_at    timestamptz,
  finished_at   timestamptz,
  error_message text,
  created_at    timestamptz not null default now(),
  -- Solo los estados finales tienen hora de fin.
  constraint job_runs_finished_at_matches_status
    check ((status in ('completed', 'failed')) = (finished_at is not null))
);

comment on table public.job_runs is
  'Ejecuciones de jobs en segundo plano (pending → processing → completed | failed). El estado processing actúa como lock.';
comment on column public.job_runs.job_name is
  'Nombre del job; hoy solo nightly_export.';
comment on column public.job_runs.target_date is
  'Día (UTC) que procesa la ejecución: clave de idempotencia junto con job_name.';
comment on column public.job_runs.started_at is
  'Momento de la transición a processing (toma del lock).';
comment on column public.job_runs.finished_at is
  'Momento de la transición a completed o failed (liberación del lock).';
comment on column public.job_runs.error_message is
  'Tipo y mensaje de la excepción si la ejecución terminó en failed.';

-- Idempotencia: ¿existe ya una ejecución completed de este job para este día?
create index if not exists job_runs_job_name_target_date_idx
  on public.job_runs (job_name, target_date);

-- Lock: como mucho una fila processing por job.
create unique index if not exists job_runs_single_processing_idx
  on public.job_runs (job_name)
  where status = 'processing';

-- Sin acceso desde la API REST pública de Supabase.
alter table public.job_runs enable row level security;

revoke all on public.job_runs from anon, authenticated;
