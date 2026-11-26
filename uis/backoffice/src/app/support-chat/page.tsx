"use client";

import Link from "next/link";
import { useEffect, useReducer, useRef, useState, type FormEvent } from "react";
import InventoryLayout from "../inventory/layout";
import { ApiError } from "@/lib/api";
import { connectChatSocket, type ChatSocket, type ChatSocketStatusInfo } from "@/lib/chat-ws";
import {
  CHAT_SESSION_STORAGE_KEY,
  CLIENT_IDS,
  DEFAULT_CLIENT_ID,
  MESSAGE_MAX_LENGTH,
  applyChatEvent,
  awaitSnapshot,
  createChatSession,
  currentUserId,
  initialChatState,
  type ChatErrorCode,
  type ChatMessage,
  type ChatState,
  type ServerEvent,
} from "@/lib/support-chat";

// Chat de soporte (Sistemas en tiempo real · Parte 2): el First-line CX agent de
// Valentina Cruz responde token a token por WebSocket. Enviar mientras responde
// interrumpe la respuesta (`interrupt_requested` con `new_input`) y empieza otra;
// «Detener» solo interrumpe. Al reconectar, la conversación se rehidrata con
// `session_snapshot`. `?session=<id>` permite a un admin/manager observar otra sesión.
// No sustituye a /knowledge (Asistente comercial del equipo de Miguel Torres).

type Action = { type: "event"; event: ServerEvent } | { type: "await_snapshot" } | { type: "reset" };

function chatReducer(state: ChatState, action: Action): ChatState {
  if (action.type === "reset") return initialChatState;
  if (action.type === "await_snapshot") return awaitSnapshot(state);
  return applyChatEvent(state, action.event);
}

const ERROR_TEXT: Record<ChatErrorCode, string> = {
  invalid_message: `El mensaje debe tener entre 1 y ${MESSAGE_MAX_LENGTH} caracteres.`,
  generation_in_progress: "El agente ya está respondiendo: envía tu mensaje para redirigirlo.",
  nothing_to_interrupt: "No había ninguna respuesta en curso.",
  forbidden: "Estás observando esta conversación: solo su dueño puede escribir.",
  agent_unavailable: "El agente no ha podido completar la respuesta. Inténtalo de nuevo en unos minutos.",
};

export default function SupportChatPage() {
  return (
    <InventoryLayout>
      <SupportChat />
    </InventoryLayout>
  );
}

function SupportChat() {
  const [ready, setReady] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [joined, setJoined] = useState(false); // vino por ?session=<id>: no se guarda en localStorage
  const [userId, setUserId] = useState<number | null>(null);
  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [connection, setConnection] = useState<ChatSocketStatusInfo>({ status: "closed", attempt: 0 });
  const [reconnectAt, setReconnectAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [input, setInput] = useState("");
  const [clientId, setClientId] = useState<string>(DEFAULT_CLIENT_ID);
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const socketRef = useRef<ChatSocket | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  // Sesión de la URL (observar) o la última propia guardada en este navegador.
  useEffect(() => {
    const joinId = new URLSearchParams(window.location.search).get("session");
    if (joinId) {
      setJoined(true);
      setSessionId(joinId);
    } else {
      try {
        const saved = localStorage.getItem(CHAT_SESSION_STORAGE_KEY);
        if (saved) setSessionId(saved);
      } catch {
        // Sin localStorage: se empieza sin sesión.
      }
    }
    setUserId(currentUserId());
    setReady(true);
  }, []);

  useEffect(() => {
    if (!sessionId) return;
    dispatch({ type: "reset" });
    const socket = connectChatSocket({
      sessionId,
      onEvent: (event) => dispatch({ type: "event", event }),
      onStatus: (info) => {
        setConnection(info);
        setReconnectAt(info.retryInMs ? Date.now() + info.retryInMs : null);
        if (info.status !== "open") dispatch({ type: "await_snapshot" });
      },
    });
    socketRef.current = socket;
    return () => {
      socket.close();
      if (socketRef.current === socket) socketRef.current = null;
    };
  }, [sessionId]);

  // Cuenta atrás de «Reconectando en N s…».
  useEffect(() => {
    if (connection.status !== "reconnecting") return;
    const interval = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(interval);
  }, [connection.status]);

  // Una sesión propia que ya no existe deja de recordarse.
  useEffect(() => {
    if (connection.status !== "not_found" || joined) return;
    try {
      localStorage.removeItem(CHAT_SESSION_STORAGE_KEY);
    } catch {
      // Sin localStorage no hay nada que limpiar.
    }
  }, [connection.status, joined]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [state.messages]);

  const session = state.session;
  const observing = Boolean(session && userId !== null && session.user_id !== userId);
  const generating = state.streaming !== null;
  const connected = connection.status === "open" && state.hydrated;
  const canWrite = connected && !observing;
  const trimmed = input.trim();

  async function newConversation() {
    setCreating(true);
    setNotice(null);
    try {
      const created = await createChatSession(clientId);
      try {
        localStorage.setItem(CHAT_SESSION_STORAGE_KEY, created.session_id);
      } catch {
        // Sin localStorage la sesión dura lo que la pestaña.
      }
      window.history.replaceState(null, "", "/support-chat");
      setJoined(false);
      setInput("");
      setSessionId(created.session_id);
    } catch (reason: unknown) {
      setNotice(reason instanceof ApiError && reason.status === 503
        ? "El chat no está disponible: la API no tiene base de datos."
        : reason instanceof Error ? reason.message : "No se pudo crear la conversación.");
    } finally {
      setCreating(false);
    }
  }

  function submit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!sessionId || !canWrite || !trimmed || trimmed.length > MESSAGE_MAX_LENGTH) return;
    // Enviar durante la respuesta la interrumpe y redirige al agente con el nuevo texto.
    const sent = socketRef.current?.send(generating
      ? { event: "interrupt_requested", data: { session_id: sessionId, new_input: trimmed } }
      : { event: "user_message", data: { session_id: sessionId, text: trimmed } });
    if (sent) setInput("");
    else setNotice("Sin conexión: el mensaje no se ha enviado.");
  }

  function stop() {
    if (!sessionId || !canWrite || !generating) return;
    socketRef.current?.send({ event: "interrupt_requested", data: { session_id: sessionId } });
  }

  const errorText = state.lastError ? ERROR_TEXT[state.lastError.code] ?? state.lastError.detail : null;

  return (
    <main className="min-h-[calc(100vh-57px)] bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      <div className="mx-auto max-w-3xl space-y-4 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-2xl font-bold">Chat de soporte</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              First-line CX agent: tracking, devoluciones y preguntas frecuentes. La respuesta se escribe en vivo;
              si va por mal camino, escribe de nuevo para redirigirla o pulsa «Detener».
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="chat-client" className="sr-only">Cliente</label>
            <select
              id="chat-client"
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
              disabled={creating}
              className="rounded-md border border-gray-300 bg-white px-2 py-2 text-sm dark:border-gray-700 dark:bg-gray-900"
            >
              {CLIENT_IDS.map((id) => <option key={id} value={id}>{id}</option>)}
            </select>
            <button
              type="button"
              onClick={() => void newConversation()}
              disabled={creating}
              className="rounded-md border border-gray-300 px-3 py-2 text-sm font-medium transition-colors hover:bg-gray-100 disabled:opacity-50 dark:border-gray-700 dark:hover:bg-gray-800"
            >
              {creating ? "Creando…" : "Nueva conversación"}
            </button>
          </div>
        </div>

        {sessionId && (
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500 dark:text-gray-400">
            <span>
              Sesión <code className="font-mono">{sessionId}</code>
              {session ? ` · cliente ${session.client_id} · ${session.status}` : ""}
            </span>
            <ConnectionBadge connection={connection} reconnectAt={reconnectAt} now={now} />
          </div>
        )}

        {observing && (
          <p role="status" className="rounded-md border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900 dark:border-sky-900 dark:bg-sky-950 dark:text-sky-200">
            <strong>Observando</strong> la conversación de otro usuario: ves los mismos tokens en vivo, pero no puedes escribir.
          </p>
        )}

        {notice && (
          <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            {notice}
          </p>
        )}

        {ready && !sessionId && (
          <p className="rounded-lg border border-dashed border-gray-300 bg-white p-6 text-center text-sm text-gray-600 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-300">
            Elige el cliente y pulsa «Nueva conversación» para empezar.
          </p>
        )}

        {sessionId && (
          <section
            aria-label="Conversación"
            aria-live="polite"
            className="h-[55vh] space-y-3 overflow-y-auto rounded-lg border border-gray-200 bg-white p-4 shadow dark:border-gray-800 dark:bg-gray-900"
          >
            {state.hydrated && state.messages.length === 0 && (
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Pregunta por un pedido, una devolución o una política. Ej.: «¿Cuál es la ventana de devolución en España?»
              </p>
            )}
            {state.messages.map((message) => <MessageBubble key={message.message_id} message={message} />)}
            <div ref={endRef} />
          </section>
        )}

        {sessionId && errorText && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">{errorText}</p>
        )}

        {sessionId && (
          <form
            onSubmit={submit}
            className="space-y-2 rounded-lg border border-gray-200 bg-white p-4 shadow dark:border-gray-800 dark:bg-gray-900"
          >
            <label htmlFor="chat-input" className="sr-only">Mensaje</label>
            <textarea
              id="chat-input"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  submit();
                }
              }}
              rows={2}
              maxLength={MESSAGE_MAX_LENGTH}
              disabled={!canWrite}
              placeholder={observing ? "Observando: solo lectura" : generating
                ? "Escribe para redirigir la respuesta en curso…"
                : "Escribe tu mensaje…"}
              className="w-full resize-y rounded-md border border-gray-300 bg-white p-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900 disabled:opacity-60 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100"
            />
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span className="text-xs text-gray-500 dark:text-gray-400">
                {input.length}/{MESSAGE_MAX_LENGTH} · Enter para enviar, Mayús+Enter para salto de línea
              </span>
              <div className="flex gap-2">
                {generating && (
                  <button
                    type="button"
                    onClick={stop}
                    disabled={!canWrite}
                    className="rounded-md border border-amber-400 px-4 py-2 text-sm font-medium text-amber-800 transition-colors hover:bg-amber-50 disabled:opacity-50 dark:text-amber-300 dark:hover:bg-amber-950"
                  >
                    Detener
                  </button>
                )}
                <button
                  type="submit"
                  disabled={!canWrite || !trimmed}
                  className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-gray-300"
                >
                  {generating ? "Redirigir" : "Enviar"}
                </button>
              </div>
            </div>
          </form>
        )}
      </div>
    </main>
  );
}

function ConnectionBadge({ connection, reconnectAt, now }: {
  connection: ChatSocketStatusInfo;
  reconnectAt: number | null;
  now: number;
}) {
  const seconds = reconnectAt ? Math.max(0, Math.ceil((reconnectAt - now) / 1000)) : 0;
  const view: Record<ChatSocketStatusInfo["status"], { text: string; dot: string }> = {
    connecting: { text: "Conectando…", dot: "bg-gray-400" },
    rehydrating: { text: "Rehidratando…", dot: "bg-sky-500" },
    open: { text: "Conectado", dot: "bg-emerald-500" },
    reconnecting: { text: `Reconectando en ${seconds} s… (intento ${connection.attempt})`, dot: "bg-amber-500" },
    unauthorized: { text: "Sesión caducada", dot: "bg-red-500" },
    forbidden: { text: "Sin acceso a esta conversación", dot: "bg-red-500" },
    not_found: { text: "La conversación no existe", dot: "bg-red-500" },
    closed: { text: "Desconectado", dot: "bg-gray-400" },
  };
  const { text, dot } = view[connection.status];
  return (
    <span role="status" className="inline-flex items-center gap-2">
      <span aria-hidden className={`h-2 w-2 rounded-full ${dot}`} />
      {text}
      {connection.status === "unauthorized" && <Link href="/login" className="underline">Iniciar sesión</Link>}
    </span>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const streaming = message.status === "streaming";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] space-y-1 rounded-lg px-3 py-2 text-sm leading-relaxed ${
          isUser
            ? "bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900"
            : "border border-gray-200 bg-gray-50 dark:border-gray-800 dark:bg-gray-950"
        }`}
      >
        {!isUser && (message.status === "interrupted" || message.status === "error") && (
          <span
            className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-medium ${
              message.status === "interrupted"
                ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200"
            }`}
          >
            {message.status === "interrupted" ? "Interrumpido" : "Error"}
          </span>
        )}
        <p className="whitespace-pre-line">
          {message.text || (streaming ? <span className="italic text-gray-400">Pensando…</span> : null)}
          {streaming && <span aria-hidden className="ml-0.5 inline-block animate-pulse">▍</span>}
        </p>
      </div>
    </div>
  );
}
