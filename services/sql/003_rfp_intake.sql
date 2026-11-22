-- TrackFlow · Hito 9 · Flujo agéntico de RFPs — Parte 1: recepción y enrutamiento.
--
-- Se ejecuta a mano en Supabase (SQL Editor) ANTES de arrancar la API con el
-- código nuevo. Es idempotente: puede ejecutarse varias veces sin error y nunca
-- borra datos. Las mismas tablas están declaradas con SQLModel en
-- `data/pipelines/rfp_intake/sql_store.py` (create_all solo las crearía sin los
-- checks ni RLS; por eso este fichero va primero).
--
-- Fuente de verdad del ticket RFP (no TinyDB ni JSON):
--   rfp_tickets              ticket + ciclo de vida + Markdown + handoff a la Parte 2
--   rfp_metadata             metadatos de la RFP (BRIEFING §2.3) + legibilidad
--   rfp_department_sections  DepartmentSection por departamento activo (key_aspects;
--                            draft/evaluación/aprobación quedan para las Partes 2 y 3)
--
-- RLS sin políticas cierra las tablas a la API REST pública de Supabase; la API
-- de TrackFlow escribe como propietaria a través del pooler de DATABASE_URL.

create table if not exists public.rfp_tickets (
  ticket_id          serial      primary key,
  rfp_id             text        not null,
  status             text        not null default 'analizando',
  stage              text        not null default 'recibido',
  raw_pdf_path       text        not null,
  original_filename  text        not null,
  file_sha256        text        not null,
  file_size_bytes    integer     not null check (file_size_bytes > 0),
  uploaded_by        text,
  markdown_chars     integer,
  markdown           text,
  classification     jsonb,
  error_stage        text,
  error_message      text,
  handoff            jsonb,
  ready_for_drafting boolean     not null default false,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint rfp_tickets_status_check check (status in (
    'analizando', 'descartado', 'analisis_completo',
    'generando_borrador', 'en_evaluación', 'needs_human_review', 'esperando_aprobación', 'terminado'
  )),
  constraint rfp_tickets_stage_check check (stage in (
    'recibido', 'convirtiendo', 'clasificando', 'extrayendo_metadatos', 'orquestando',
    'analizando_departamentos', 'sintetizando', 'completado', 'descartado', 'error'
  ))
);

create unique index if not exists rfp_tickets_rfp_id_idx on public.rfp_tickets (rfp_id);
create index if not exists rfp_tickets_status_idx on public.rfp_tickets (status);
create index if not exists rfp_tickets_file_sha256_idx on public.rfp_tickets (file_sha256);
-- Cola de la Parte 2: tickets con análisis completo pendientes de redactar.
create index if not exists rfp_tickets_ready_for_drafting_idx
  on public.rfp_tickets (ticket_id) where ready_for_drafting and status = 'analisis_completo';

comment on table public.rfp_tickets is
  'Ticket de una RFP subida desde el backoffice: estado (BRIEFING §2.3), PDF en data/raw/rfp/ y handoff a la Parte 2.';
comment on column public.rfp_tickets.stage is
  'Etapa interna del pipeline rfp_intake; error + error_stage si falló a mitad (el estado sigue en analizando).';
comment on column public.rfp_tickets.handoff is
  'Contrato trackflow.rfp_intake.handoff/v1: ticket_id + estructura de workstreams del synthesizer (key_aspects por departamento).';
comment on column public.rfp_tickets.ready_for_drafting is
  'Bandera de cola: la Parte 2 toma los tickets con true y status analisis_completo.';

create table if not exists public.rfp_metadata (
  ticket_id          integer     primary key references public.rfp_tickets (ticket_id) on delete cascade,
  client_name        text,
  client_reference   text,
  client_country     text check (client_country in ('United States', 'Spain')),
  currency           text check (currency in ('USD', 'EUR')),
  services_requested jsonb       not null default '[]'::jsonb,
  monthly_volume     integer check (monthly_volume >= 0),
  deadline           date,
  deadline_text      text,
  budget_range       text,
  contact            jsonb       not null default '{}'::jsonb,
  departments_needed jsonb       not null default '[]'::jsonb,
  readability        jsonb       not null default '{}'::jsonb,
  word_count         integer,
  estimated_tokens   integer,
  extraction_source  text        not null default 'rules',
  warnings           jsonb       not null default '[]'::jsonb,
  created_at         timestamptz not null default now()
);

comment on table public.rfp_metadata is
  'Metadatos de la RFP (BRIEFING §2.3) y métricas de legibilidad para anticipar el costo de procesamiento.';

create table if not exists public.rfp_department_sections (
  id                 serial      primary key,
  ticket_id          integer     not null references public.rfp_tickets (ticket_id) on delete cascade,
  department_id      text        not null check (department_id in ('warehouse', 'lastmile', 'reverse')),
  department_name    text        not null,
  responsible        text        not null,
  key_aspects        jsonb       not null default '[]'::jsonb,
  open_questions     jsonb       not null default '[]'::jsonb,
  excerpts           jsonb       not null default '[]'::jsonb,
  source             text        not null default 'rules',
  warnings           jsonb       not null default '[]'::jsonb,
  draft_content      text,
  evaluation_results jsonb,
  approval_status    text,
  approver           text,
  approved_at        timestamptz,
  created_at         timestamptz not null default now(),
  constraint rfp_department_sections_ticket_dept_key unique (ticket_id, department_id)
);

create index if not exists rfp_department_sections_ticket_id_idx on public.rfp_department_sections (ticket_id);

comment on table public.rfp_department_sections is
  'DepartmentSection (BRIEFING §2.3): key_aspects en la Parte 1; borrador, evaluación y aprobación en las Partes 2 y 3.';

alter table public.rfp_tickets enable row level security;
alter table public.rfp_metadata enable row level security;
alter table public.rfp_department_sections enable row level security;

-- Verificación (debe devolver 3 filas: rfp_tickets 18, rfp_metadata 18, rfp_department_sections 16):
-- select table_name, count(*) as columns
-- from information_schema.columns
-- where table_schema = 'public' and table_name like 'rfp_%'
-- group by table_name order by table_name;
