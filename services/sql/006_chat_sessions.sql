-- TrackFlow · Sistemas en tiempo real — Parte 2: chat del First-line CX agent por WebSocket.
--
-- Se ejecuta a mano en Supabase (SQL Editor) ANTES de arrancar la API con el
-- código nuevo. Es idempotente: puede ejecutarse varias veces sin error y nunca
-- borra datos. Las mismas tablas están declaradas con SQLModel en
-- `services/agent/chat/store.py` (create_all solo las crearía sin los checks ni RLS).
--
-- Fuente de la rehidratación del chat (no el checkpointer de LangGraph):
--   chat_sessions  ChatSession del BRIEFING: session_id, agent_id (first_line_cx),
--                  user_id (usuario del JWT que chatea), client_id, status, created_at
--   chat_messages  turnos del usuario y respuestas del agente, incluidas las
--                  interrumpidas (nunca se borran ni se sobrescriben)
--
-- RLS sin políticas cierra las tablas a la API REST pública de Supabase; la API
-- de TrackFlow escribe como propietaria a través del pooler de DATABASE_URL.

create table if not exists public.chat_sessions (
  session_id  text        primary key,
  agent_id    text        not null default 'first_line_cx',
  user_id     integer     not null,
  client_id   text        not null,
  status      text        not null default 'active',
  created_at  timestamptz not null default now(),
  constraint chat_sessions_session_id_check check (session_id ~ '^chat_[0-9a-f]{12}$'),
  constraint chat_sessions_agent_id_check check (agent_id = 'first_line_cx'),
  constraint chat_sessions_client_id_check check (client_id ~ '^[A-Za-z0-9_-]{1,40}$'),
  constraint chat_sessions_status_check check (status in ('active', 'interrupted', 'closed'))
);

create index if not exists chat_sessions_user_id_idx on public.chat_sessions (user_id);

comment on table public.chat_sessions is
  'ChatSession (BRIEFING Parte 2): conversación de un cliente con el First-line CX agent.';

create table if not exists public.chat_messages (
  message_id  text        primary key,
  session_id  text        not null references public.chat_sessions (session_id) on delete cascade,
  role        text        not null,
  text        text        not null default '',
  status      text        not null,
  run_id      text,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint chat_messages_message_id_check check (message_id ~ '^msg_[0-9a-f]{12}$'),
  constraint chat_messages_role_check check (role in ('user', 'assistant')),
  constraint chat_messages_status_check check (status in ('streaming', 'completed', 'interrupted', 'error'))
);

create index if not exists chat_messages_session_id_created_at_idx on public.chat_messages (session_id, created_at);

comment on table public.chat_messages is
  'Mensajes del chat: user (completed) y assistant (streaming → completed / interrupted / error). run_id = trace del agente.';

alter table public.chat_sessions enable row level security;
alter table public.chat_messages enable row level security;

-- Verificación (debe devolver 2 filas: chat_messages 8, chat_sessions 6):
-- select table_name, count(*) as columns
-- from information_schema.columns
-- where table_schema = 'public' and table_name like 'chat_%'
-- group by table_name order by table_name;
