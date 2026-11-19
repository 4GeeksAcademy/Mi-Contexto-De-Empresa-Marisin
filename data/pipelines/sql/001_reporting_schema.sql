-- TrackFlow · Data Pipeline 2/3 · Esquema `reporting` del Pipeline de Desempeño de Negocio.
--
-- Se ejecuta a mano en Supabase (SQL Editor). Es idempotente: puede ejecutarse
-- varias veces sin error y nunca borra datos.
--
-- - reporting.weekly_warehouse_client_performance: tabla de destino, con el
--   nombre y las columnas exactas del BRIEFING de data pipelines (§5).
-- - reporting.pipeline_runs: log de ejecución (PIPELINE_DESIGN.md §5.2 y §8).
--
-- El pipeline lee public.telemetry_events en modo solo lectura: este script no
-- la toca. RLS sin políticas cierra ambas tablas a la API REST pública de
-- Supabase; el backend las usa como propietario a través de DATABASE_URL.

create schema if not exists reporting;

create table if not exists reporting.weekly_warehouse_client_performance (
  id uuid primary key default gen_random_uuid(),
  warehouse text not null,
  client_id text not null,
  week_start date not null,
  inbound_units_count integer not null default 0,
  outbound_orders_count integer not null default 0,
  stockout_events_count integer not null default 0,
  discrepancy_events_count integer not null default 0,
  discrepancy_rate numeric not null default 0,
  computed_at timestamptz not null default now(),
  unique (warehouse, client_id, week_start)
);

comment on table reporting.weekly_warehouse_client_performance is
  'Reporte Semanal de Desempeño por Almacén y Cliente: una fila por almacén, cliente y semana ISO (UTC).';
comment on column reporting.weekly_warehouse_client_performance.computed_at is
  'now() de la transacción de carga que cambió la fila por última vez; coincide con pipeline_runs.loaded_at.';

create table if not exists reporting.pipeline_runs (
  run_id               uuid        primary key,
  pipeline_name        text        not null,
  trigger              text        not null check (trigger in ('scheduled', 'manual', 'backfill')),
  triggered_by         text,
  prefect_flow_run_id  uuid,
  status               text        not null check (status in ('running', 'completed', 'failed')),
  last_completed_phase text        check (last_completed_phase in ('extract', 'transform', 'validate', 'load')),
  window_start         date        not null,
  window_end           date        not null,
  started_at           timestamptz not null default now(),
  heartbeat_at         timestamptz not null default now(),
  finished_at          timestamptz,
  loaded_at            timestamptz,
  duration_ms          integer,
  events_extracted     integer     not null default 0,
  duplicates_dropped   integer     not null default 0,
  events_excluded      integer     not null default 0,
  events_rejected      integer     not null default 0,
  events_by_type       jsonb       not null default '{}'::jsonb,
  rows_inserted        integer     not null default 0,
  rows_updated         integer     not null default 0,
  rows_unchanged       integer     not null default 0,
  rows_deleted         integer     not null default 0,
  source_max_timestamp timestamptz,
  capture_coverage     jsonb       not null default '{}'::jsonb,
  warnings             jsonb       not null default '[]'::jsonb,
  error_type           text,
  error_message        text
);

comment on table reporting.pipeline_runs is
  'Log de ejecución de los pipelines de reporting: una fila por corrida.';

create index if not exists pipeline_runs_latest_idx
  on reporting.pipeline_runs (pipeline_name, started_at desc);

-- Sin acceso desde la API REST pública de Supabase.
alter table reporting.weekly_warehouse_client_performance enable row level security;
alter table reporting.pipeline_runs enable row level security;

revoke all on schema reporting from anon, authenticated;
revoke all on all tables in schema reporting from anon, authenticated;
