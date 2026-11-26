import { getAuthToken } from "./api";
import { backoffDelay } from "./sse";
import { parseServerEvent, type ClientEvent, type ServerEvent } from "./support-chat";

// Cliente WebSocket del chat de soporte (`WS /agent/chat/sessions/{id}/ws?token=<JWT>`).
// El navegador no permite `Authorization` en el handshake: el mismo JWT va en `?token=`.
// Pasa por el proxy `/api/backend` de next.config.ts (en Codespaces el navegador no llega a :8000).
//
// Reconexión: backoff 1, 2, 4, 8, 16 s, tope 30 s, jitter ±20 % (el mismo `backoffDelay`
// que el SSE); vuelve a 1 s tras recibir un `session_snapshot`. Los cierres 4401, 4403 y
// 4404 no se reintentan. `offline` cierra el socket; `online` reconecta sin esperar.
// Tras abrir, el estado es «rehidratando» hasta el `session_snapshot` (el reductor
// descarta lo que llegue antes). Logs `[chat-ws]` de cada intento y retardo.

const API_PATH = "/api/backend"; // proxy de next.config.ts (el mismo que usa api.ts)

export const CLOSE_UNAUTHORIZED = 4401;
export const CLOSE_FORBIDDEN = 4403;
export const CLOSE_NOT_FOUND = 4404;

export type ChatSocketStatus =
  | "connecting"
  | "rehydrating"
  | "open"
  | "reconnecting"
  | "unauthorized"
  | "forbidden"
  | "not_found"
  | "closed";

export interface ChatSocketStatusInfo {
  status: ChatSocketStatus;
  attempt: number;
  retryInMs?: number;
  closeCode?: number;
}

export interface ConnectChatSocketOptions {
  sessionId: string;
  onEvent: (event: ServerEvent) => void;
  onStatus?: (info: ChatSocketStatusInfo) => void;
}

export interface ChatSocket {
  send: (event: ClientEvent) => boolean;
  close: () => void;
}

const FINAL_CLOSE: Record<number, ChatSocketStatus> = {
  [CLOSE_UNAUTHORIZED]: "unauthorized",
  [CLOSE_FORBIDDEN]: "forbidden",
  [CLOSE_NOT_FOUND]: "not_found",
};

export function chatSocketUrl(sessionId: string, token: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const path = `${API_PATH}/agent/chat/sessions/${encodeURIComponent(sessionId)}/ws`;
  return `${scheme}://${window.location.host}${path}?token=${encodeURIComponent(token)}`;
}

export function connectChatSocket({ sessionId, onEvent, onStatus }: ConnectChatSocketOptions): ChatSocket {
  let socket: WebSocket | null = null;
  let attempt = 0;
  let timer = 0;
  let stopped = false;

  const status = (info: ChatSocketStatusInfo) => onStatus?.(info);

  function scheduleReconnect(closeCode?: number) {
    const delay = backoffDelay(attempt);
    attempt += 1;
    console.info(`[chat-ws] reconectando en ${(delay / 1000).toFixed(1)} s (intento ${attempt})`);
    status({ status: "reconnecting", attempt, retryInMs: delay, closeCode });
    window.clearTimeout(timer);
    timer = window.setTimeout(open, delay);
  }

  function open() {
    timer = 0;
    if (stopped) return;
    const token = getAuthToken();
    if (!token) {
      console.warn("[chat-ws] sin token: sesión caducada, no se reintenta");
      status({ status: "unauthorized", attempt });
      return;
    }
    console.info(`[chat-ws] conectando a la sesión ${sessionId}${attempt ? ` (intento ${attempt})` : ""}`);
    if (attempt === 0) status({ status: "connecting", attempt });
    const current = new WebSocket(chatSocketUrl(sessionId, token));
    socket = current;

    current.onopen = () => {
      if (socket !== current) return;
      console.info("[chat-ws] abierto: esperando session_snapshot");
      status({ status: "rehydrating", attempt });
    };
    current.onmessage = (message: MessageEvent) => {
      if (socket !== current || typeof message.data !== "string") return;
      const event = parseServerEvent(message.data);
      if (!event) {
        console.warn("[chat-ws] frame desconocido descartado");
        return;
      }
      if (event.event === "session_snapshot") {
        console.info(`[chat-ws] session_snapshot: ${event.data.messages.length} mensajes` +
          (event.data.active_generation ? `, respuesta en curso desde sequence ${event.data.active_generation.sequence}` : ""));
        attempt = 0; // backoff reiniciado: la sesión está rehidratada
        status({ status: "open", attempt });
      }
      onEvent(event);
    };
    current.onclose = (close: CloseEvent) => {
      if (socket !== current) return;
      socket = null;
      if (stopped) return;
      const final = FINAL_CLOSE[close.code];
      if (final) {
        console.warn(`[chat-ws] cerrado con ${close.code} (${close.reason || final}): no se reintenta`);
        status({ status: final, attempt, closeCode: close.code });
        return;
      }
      console.warn(`[chat-ws] conexión perdida (código ${close.code}${close.reason ? `, ${close.reason}` : ""})`);
      scheduleReconnect(close.code);
    };
    // `onerror` siempre va seguido de `onclose`: la reconexión se decide allí.
    current.onerror = () => console.warn("[chat-ws] error en el socket");
  }

  function handleOffline() {
    console.warn("[chat-ws] el navegador está offline: se cierra el socket");
    socket?.close();
  }

  function handleOnline() {
    if (stopped || socket) return;
    console.info("[chat-ws] de vuelta online: se reconecta ya");
    window.clearTimeout(timer);
    open();
  }

  window.addEventListener("offline", handleOffline);
  window.addEventListener("online", handleOnline);
  open();

  return {
    send(event: ClientEvent) {
      if (!socket || socket.readyState !== WebSocket.OPEN) return false;
      socket.send(JSON.stringify(event));
      return true;
    },
    close() {
      stopped = true;
      window.clearTimeout(timer);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
      const current = socket;
      socket = null;
      current?.close(1000, "client closed");
      status({ status: "closed", attempt });
    },
  };
}
