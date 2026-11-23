-- TrackFlow · Hito 9 · Flujo agéntico de RFPs — Parte 2: generación y evaluación de respuestas.
--
-- Se ejecuta a mano en Supabase (SQL Editor) DESPUÉS de 003_rfp_intake.sql y ANTES
-- de arrancar la API con el código nuevo. Es idempotente y nunca borra datos.
-- Las mismas columnas están declaradas con SQLModel en
-- `data/pipelines/rfp_intake/sql_store.py`.
--
-- Qué añade:
--   rfp_tickets              drafting_handoff (contrato trackflow.rfp_drafting.handoff/v1
--                            para la Parte 3) + bandera ready_for_approval; etapas
--                            internas de la Parte 2 en el check de `stage`.
--   rfp_department_sections  draft_status, iterations, evaluation_history, draft_source.
--                            draft_content y evaluation_results (último EvaluationResult)
--                            ya existían desde la Parte 1.
-- Los estados del ticket de la Parte 2 (generando_borrador, en_evaluación,
-- needs_human_review) ya estaban permitidos en `rfp_tickets_status_check`.

alter table public.rfp_tickets add column if not exists drafting_handoff jsonb;
alter table public.rfp_tickets add column if not exists ready_for_approval boolean not null default false;

alter table public.rfp_tickets drop constraint if exists rfp_tickets_stage_check;
alter table public.rfp_tickets add constraint rfp_tickets_stage_check check (stage in (
  'recibido', 'convirtiendo', 'clasificando', 'extrayendo_metadatos', 'orquestando',
  'analizando_departamentos', 'sintetizando', 'completado', 'descartado', 'error',
  'generando_secciones', 'evaluando_secciones', 'borradores_listos'
));

-- Cola de la Parte 3: tickets con borradores evaluados listos para aprobación humana.
create index if not exists rfp_tickets_ready_for_approval_idx
  on public.rfp_tickets (ticket_id) where ready_for_approval;

comment on column public.rfp_tickets.drafting_handoff is
  'Handoff de la Parte 2 a la Parte 3 (trackflow.rfp_drafting.handoff/v1): secciones, EvaluationResult y needs_human_review.';
comment on column public.rfp_tickets.ready_for_approval is
  'Bandera de cola: la Parte 3 toma los tickets con true (también los que tienen secciones needs_human_review).';

alter table public.rfp_department_sections add column if not exists draft_status text;
alter table public.rfp_department_sections add column if not exists iterations integer not null default 0;
alter table public.rfp_department_sections add column if not exists evaluation_history jsonb not null default '[]'::jsonb;
alter table public.rfp_department_sections add column if not exists draft_source text;

alter table public.rfp_department_sections drop constraint if exists rfp_department_sections_draft_status_check;
alter table public.rfp_department_sections add constraint rfp_department_sections_draft_status_check check (
  draft_status is null or draft_status in ('generando_borrador', 'en_evaluación', 'evaluacion_superada', 'needs_human_review')
);
alter table public.rfp_department_sections drop constraint if exists rfp_department_sections_iterations_check;
alter table public.rfp_department_sections add constraint rfp_department_sections_iterations_check check (iterations >= 0);

comment on column public.rfp_department_sections.evaluation_results is
  'Último EvaluationResult de la sección: readability {pass, score, details}, relevance {pass, missing_aspects}, compliance {pass, rule_ids, violations}, overall_pass, feedback_for_generator.';
comment on column public.rfp_department_sections.evaluation_history is
  'Una entrada por iteración del ciclo generador-evaluador (borrador, resultado y feedback).';

-- Verificación (debe devolver 3 filas: rfp_department_sections 20, rfp_metadata 18, rfp_tickets 20):
-- select table_name, count(*) as columns
-- from information_schema.columns
-- where table_schema = 'public' and table_name like 'rfp_%'
-- group by table_name order by table_name;
