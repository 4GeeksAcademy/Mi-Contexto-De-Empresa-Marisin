-- TrackFlow · Hito 9 · Flujo agéntico de RFPs — Parte 3: aprobación humana y cierre del documento.
--
-- Se ejecuta a mano en Supabase (SQL Editor) DESPUÉS de 004_rfp_drafting.sql y ANTES
-- de arrancar la API con el código nuevo. Es idempotente y nunca borra datos.
-- Las mismas columnas y tablas están declaradas con SQLModel en
-- `data/pipelines/rfp_intake/sql_store.py`.
--
-- Qué añade:
--   rfp_tickets              etapas internas de la Parte 3 en el check de `stage`
--                            (los estados esperando_aprobación y terminado ya estaban
--                            permitidos en `rfp_tickets_status_check`).
--   rfp_department_sections  approval_round, approval_comment, approval_requested_at
--                            (KPI de tiempo de aprobación, BRIEFING §3) y approval_history;
--                            check de approval_status. approval_status, approver y
--                            approved_at ya existían desde la Parte 1 (BRIEFING §2.3).
--   rfp_final_documents      FinalDocument (BRIEFING §2.3): ticket_id, sections, currency,
--                            generated_at + el Markdown que se entrega a Ventas.
--   rfp_trace_events         una fila por ejecución de nodo (Partes 1, 2 y 3): agente,
--                            input, output y timestamps, en orden.
-- El estado de los grafos de la Parte 3 (checkpoints de LangGraph) NO va aquí: vive en
-- el checkpointer SQLite (data/checkpoints/rfp_approval.sqlite).

alter table public.rfp_tickets drop constraint if exists rfp_tickets_stage_check;
alter table public.rfp_tickets add constraint rfp_tickets_stage_check check (stage in (
  'recibido', 'convirtiendo', 'clasificando', 'extrayendo_metadatos', 'orquestando',
  'analizando_departamentos', 'sintetizando', 'completado', 'descartado', 'error',
  'generando_secciones', 'evaluando_secciones', 'borradores_listos',
  'esperando_aprobaciones', 'arbitrando', 'revisando_secciones', 'generando_documento',
  'seccion_rechazada', 'documento_final'
));

alter table public.rfp_department_sections add column if not exists approval_round integer not null default 0;
alter table public.rfp_department_sections add column if not exists approval_comment text;
alter table public.rfp_department_sections add column if not exists approval_requested_at timestamptz;
alter table public.rfp_department_sections add column if not exists approval_history jsonb not null default '[]'::jsonb;

alter table public.rfp_department_sections drop constraint if exists rfp_department_sections_approval_status_check;
alter table public.rfp_department_sections add constraint rfp_department_sections_approval_status_check check (
  approval_status is null or approval_status in ('pendiente', 'cambios_solicitados', 'aprobada', 'rechazada')
);
alter table public.rfp_department_sections drop constraint if exists rfp_department_sections_approval_round_check;
alter table public.rfp_department_sections add constraint rfp_department_sections_approval_round_check check (approval_round >= 0);

comment on column public.rfp_department_sections.approval_status is
  'Parte 3: pendiente (rama interrumpida esperando al responsable), cambios_solicitados, aprobada o rechazada.';
comment on column public.rfp_department_sections.approval_history is
  'Una entrada por decisión del responsable o del árbitro (decision, approver, comment, round, decided_at).';

create table if not exists public.rfp_final_documents (
  ticket_id     integer     primary key references public.rfp_tickets (ticket_id) on delete cascade,
  contract      text        not null default 'trackflow.rfp_final_document/v1',
  client_name   text,
  currency      text check (currency in ('USD', 'EUR')),
  sections      jsonb       not null default '[]'::jsonb,
  arbitrations  jsonb       not null default '[]'::jsonb,
  metrics       jsonb       not null default '{}'::jsonb,
  markdown      text        not null,
  delivered_to  text        not null,
  generated_at  timestamptz not null
);

comment on table public.rfp_final_documents is
  'FinalDocument (BRIEFING §2.3): secciones aprobadas por cada responsable, moneda y fecha; Markdown para Ventas.';

create table if not exists public.rfp_trace_events (
  id            serial      primary key,
  ticket_id     integer     not null references public.rfp_tickets (ticket_id) on delete cascade,
  graph         text        not null,
  thread_id     text,
  department_id text,
  node          text        not null,
  agent         text        not null,
  status        text        not null default 'ok' check (status in ('ok', 'interrupted', 'error')),
  input         jsonb       not null default '{}'::jsonb,
  output        jsonb       not null default '{}'::jsonb,
  started_at    timestamptz,
  finished_at   timestamptz not null default now(),
  duration_ms   integer
);

create index if not exists rfp_trace_events_ticket_id_idx on public.rfp_trace_events (ticket_id, id);

comment on table public.rfp_trace_events is
  'Traza de cada ejecución de nodo de los grafos rfp_intake, rfp_drafting, rfp_approval y rfp_department_approval.';

alter table public.rfp_final_documents enable row level security;
alter table public.rfp_trace_events enable row level security;

-- Verificación (debe devolver 5 filas: rfp_department_sections 24, rfp_final_documents 10,
-- rfp_metadata 18, rfp_trace_events 13, rfp_tickets 20):
-- select table_name, count(*) as columns
-- from information_schema.columns
-- where table_schema = 'public' and table_name like 'rfp_%'
-- group by table_name order by table_name;
