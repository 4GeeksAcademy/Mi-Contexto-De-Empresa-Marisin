import { fetchWithAuth, getAuthToken } from "./api";

// Chat del First-line CX agent por WebSocket (Sistemas en tiempo real · Parte 2).
// Contrato de `services/agent/chat/schemas.py`: sobre `{event, data}` y todo `data`
// lleva `session_id`. Nombres del BRIEFING (ChatSession, token_chunk,
// interrupt_requested, generation_interrupted, generation_completed,
// session_snapshot, user_message) + `generation_started` y `chat_error`.

export const CHAT_SESSION_STORAGE_KEY = "trackflow.chat_session_id";
export const MESSAGE_MAX_LENGTH = 500;
// client_id reales del sistema (los de reporting: `toClientId(client_name)` de los productos).
export const CLIENT_IDS = ["ecowear_usa", "nova_beauty", "hydrolife"] as const;
export const DEFAULT_CLIENT_ID = CLIENT_IDS[0];

export type ChatSessionStatus = "active" | "interrupted" | "closed";
export type ChatMessageRole = "user" | "assistant";
export type ChatMessageStatus = "streaming" | "completed" | "interrupted" | "error";
export type AgentStatus = "answered" | "no_context" | "tool_fallback" | "memory_resolved" | "blocked" | "redirected";
export type AgentSource = "incidents" | "inventory" | "rag";
export type ChatErrorCode =
  | "invalid_message"
  | "generation_in_progress"
  | "nothing_to_interrupt"
  | "forbidden"
  | "agent_unavailable";

export interface ChatSession {
  session_id: string;
  agent_id: "first_line_cx";
  user_id: number;
  client_id: string;
  status: ChatSessionStatus;
  created_at: string;
}

export interface ChatMessage {
  message_id: string;
  session_id: string;
  role: ChatMessageRole;
  text: string;
  status: ChatMessageStatus;
  run_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ActiveGeneration {
  message_id: string;
  text: string;
  sequence: number;
}

export interface ChatErrorData {
  session_id: string;
  code: ChatErrorCode;
  detail: string;
  message_id?: string | null;
}

// ── servidor → cliente ──────────────────────────────────────────────────────
export type ServerEvent =
  | {
      event: "session_snapshot";
      data: { session_id: string; session: ChatSession; messages: ChatMessage[]; active_generation: ActiveGeneration | null };
    }
  | { event: "user_message"; data: { session_id: string; message_id: string; text: string; created_at: string } }
  | { event: "generation_started"; data: { session_id: string; message_id: string } }
  | { event: "token_chunk"; data: { session_id: string; message_id: string; token: string; sequence: number } }
  | { event: "generation_interrupted"; data: { session_id: string; message_id: string; status: "interrupted" } }
  | {
      event: "generation_completed";
      data: { session_id: string; message_id: string; answer: string; status: AgentStatus; sources: AgentSource[] };
    }
  | { event: "chat_error"; data: ChatErrorData };

// ── cliente → servidor ──────────────────────────────────────────────────────
export type ClientEvent =
  | { event: "user_message"; data: { session_id: string; text: string } }
  | { event: "interrupt_requested"; data: { session_id: string; new_input?: string } };

const SERVER_EVENTS = new Set<ServerEvent["event"]>([
  "session_snapshot",
  "user_message",
  "generation_started",
  "token_chunk",
  "generation_interrupted",
  "generation_completed",
  "chat_error",
]);

export function parseServerEvent(raw: string): ServerEvent | null {
  try {
    const value = JSON.parse(raw) as { event?: unknown; data?: unknown };
    if (typeof value.event !== "string" || !SERVER_EVENTS.has(value.event as ServerEvent["event"])) return null;
    if (!value.data || typeof value.data !== "object") return null;
    return value as ServerEvent;
  } catch {
    return null;
  }
}

export async function createChatSession(clientId: string): Promise<ChatSession> {
  return (await fetchWithAuth("/agent/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId }),
  })) as ChatSession;
}

// Id del usuario del JWT (`sub`) para saber si eres el dueño o un observador.
// Solo para la UI: el servidor decide los permisos (4403 / `chat_error forbidden`).
export function currentUserId(): number | null {
  const token = getAuthToken();
  const payload = token?.split(".")[1];
  if (!payload) return null;
  try {
    const json = atob(payload.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(payload.length / 4) * 4, "="));
    const sub = Number((JSON.parse(json) as { sub?: unknown }).sub);
    return Number.isSafeInteger(sub) && sub > 0 ? sub : null;
  } catch {
    return null;
  }
}

// ── estado y reductor puro ──────────────────────────────────────────────────
export interface ChatState {
  session: ChatSession | null;
  messages: ChatMessage[];
  // Respuesta en curso y el último `sequence` aplicado (dedupe de la ventana de reconexión).
  streaming: { message_id: string; sequence: number } | null;
  // Hasta el `session_snapshot` de cada conexión se descarta todo lo demás (D16).
  hydrated: boolean;
  lastError: ChatErrorData | null;
  lastStatus: AgentStatus | null;
}

export const initialChatState: ChatState = {
  session: null,
  messages: [],
  streaming: null,
  hydrated: false,
  lastError: null,
  lastStatus: null,
};

// Conexión nueva (o reconexión): se conserva lo pintado, pero hasta el snapshot no se aplica nada.
export function awaitSnapshot(state: ChatState): ChatState {
  return { ...state, hydrated: false };
}

function updateMessage(messages: ChatMessage[], messageId: string, change: Partial<ChatMessage>): ChatMessage[] {
  return messages.map((message) => (message.message_id === messageId ? { ...message, ...change } : message));
}

function withSessionStatus(session: ChatSession | null, status: ChatSessionStatus): ChatSession | null {
  return session ? { ...session, status } : session;
}

function placeholder(sessionId: string, messageId: string, role: ChatMessageRole, text: string, status: ChatMessageStatus,
  createdAt?: string): ChatMessage {
  const now = createdAt ?? new Date().toISOString();
  return { message_id: messageId, session_id: sessionId, role, text, status, created_at: now, updated_at: now };
}

export function applyChatEvent(state: ChatState, event: ServerEvent): ChatState {
  if (event.event === "session_snapshot") {
    const { session, messages, active_generation: active } = event.data;
    let next = messages.map((message) => ({ ...message }));
    if (active) {
      const exists = next.some((message) => message.message_id === active.message_id);
      next = exists
        ? updateMessage(next, active.message_id, { text: active.text, status: "streaming" })
        : [...next, placeholder(session.session_id, active.message_id, "assistant", active.text, "streaming")];
    }
    return {
      ...state,
      session,
      messages: next,
      streaming: active ? { message_id: active.message_id, sequence: active.sequence } : null,
      hydrated: true,
      lastError: null,
    };
  }
  if (!state.hydrated) return state; // antes del snapshot no se aplica nada

  const known = (messageId: string) => state.messages.find((message) => message.message_id === messageId);
  switch (event.event) {
    case "user_message": {
      if (known(event.data.message_id)) return state;
      return {
        ...state,
        session: withSessionStatus(state.session, "active"),
        messages: [...state.messages, placeholder(event.data.session_id, event.data.message_id, "user", event.data.text,
          "completed", event.data.created_at)],
        lastError: null,
      };
    }
    case "generation_started": {
      const streaming = { message_id: event.data.message_id, sequence: 0 };
      if (known(event.data.message_id)) return { ...state, streaming };
      return {
        ...state,
        streaming,
        messages: [...state.messages, placeholder(event.data.session_id, event.data.message_id, "assistant", "", "streaming")],
      };
    }
    case "token_chunk": {
      const { message_id: messageId, token, sequence } = event.data;
      const message = known(messageId);
      if (message && message.status !== "streaming") return state; // interrumpido o terminado: ni un token más
      const last = state.streaming?.message_id === messageId ? state.streaming.sequence : 0;
      if (sequence <= last) return state; // ya incluido en el snapshot o repetido
      const messages = message
        ? updateMessage(state.messages, messageId, { text: message.text + token })
        : [...state.messages, placeholder(event.data.session_id, messageId, "assistant", token, "streaming")];
      return { ...state, messages, streaming: { message_id: messageId, sequence } };
    }
    case "generation_interrupted": {
      return {
        ...state,
        session: withSessionStatus(state.session, "interrupted"),
        messages: updateMessage(state.messages, event.data.message_id, { status: "interrupted" }),
        streaming: state.streaming?.message_id === event.data.message_id ? null : state.streaming,
      };
    }
    case "generation_completed": {
      // `answer` es el texto definitivo (pasado por la guardia de salida): sustituye a lo streameado.
      const { message_id: messageId, answer } = event.data;
      const messages = known(messageId)
        ? updateMessage(state.messages, messageId, { text: answer, status: "completed" })
        : [...state.messages, placeholder(event.data.session_id, messageId, "assistant", answer, "completed")];
      return {
        ...state,
        messages,
        streaming: state.streaming?.message_id === messageId ? null : state.streaming,
        lastStatus: event.data.status,
      };
    }
    case "chat_error": {
      const { code, message_id: messageId } = event.data;
      const failed = messageId && (code === "agent_unavailable" || code === "invalid_message") ? messageId : null;
      return {
        ...state,
        lastError: event.data,
        messages: failed ? updateMessage(state.messages, failed, { status: "error" }) : state.messages,
        streaming: failed && state.streaming?.message_id === failed ? null : state.streaming,
      };
    }
  }
}
