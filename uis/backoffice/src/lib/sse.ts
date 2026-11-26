import { getAuthToken } from "./api";

// Cliente SSE con `fetch` + `ReadableStream` (no `EventSource`: no permite enviar
// `Authorization: Bearer`). Lo usa el hook de notificaciones de RFP contra
// `GET /realtime/events`, a través del mismo proxy `/api/backend` que `api.ts`.
//
// Recuperación: guarda el último `id:` recibido y lo reenvía como `Last-Event-ID`
// al reconectar; el servidor reenvía lo perdido o manda `event: resync`.
// Backoff 1 s, 2 s, 4 s, 8 s, 16 s, máx. 30 s, con jitter ±20 %; vuelve a 1 s tras
// abrir bien. Un 401 no reintenta. Si en 45 s no llega ni un byte (el servidor
// manda `: keep-alive` cada 15 s) o el navegador pasa a offline, se corta y se
// reconecta. El `retry:` del servidor es para clientes `EventSource` (curl,
// otros); aquí manda el backoff.

const API_URL = "/api/backend"; // proxy de next.config.ts (el mismo que usa api.ts)

export const BACKOFF_BASE_MS = 1000;
export const BACKOFF_MAX_MS = 30000;
export const BACKOFF_JITTER = 0.2;
export const HEARTBEAT_TIMEOUT_MS = 45000;

export interface SseMessage {
  event: string;
  data: string;
  id: string | null;
}

export type SseConnectionStatus = "connecting" | "open" | "reconnecting" | "unauthorized" | "closed";

export interface SseStatusInfo {
  status: SseConnectionStatus;
  attempt: number;
  retryInMs?: number;
}

export interface ConnectSseOptions {
  path: string;
  onEvent: (message: SseMessage) => void;
  onStatus?: (info: SseStatusInfo) => void;
  signal: AbortSignal;
}

// ── parser de frames (WHATWG, «event stream interpretation») ────────────────
export class SseParser {
  lastEventId: string | null;
  retry: number | null = null;
  private buffer = "";
  private data: string[] = [];
  private eventType = "";
  private started = false;

  constructor(lastEventId: string | null = null) {
    this.lastEventId = lastEventId;
  }

  feed(chunk: string): SseMessage[] {
    this.buffer += chunk;
    if (!this.started && this.buffer.length > 0) {
      this.started = true;
      if (this.buffer.charCodeAt(0) === 0xfeff) this.buffer = this.buffer.slice(1);
    }
    const messages: SseMessage[] = [];
    while (true) {
      const match = /\r\n|\r|\n/.exec(this.buffer);
      if (!match) break;
      // Un `\r` al final puede ser la mitad de un `\r\n` partido entre dos chunks.
      if (match[0] === "\r" && match.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      const message = this.line(line);
      if (message) messages.push(message);
    }
    return messages;
  }

  private line(line: string): SseMessage | null {
    if (line === "") return this.dispatch();
    if (line.startsWith(":")) return null; // comentario (`: connected`, `: keep-alive`)
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "data") this.data.push(value);
    else if (field === "event") this.eventType = value;
    else if (field === "id" && !value.includes("\0")) this.lastEventId = value;
    else if (field === "retry" && /^\d+$/.test(value)) this.retry = Number(value);
    return null;
  }

  // Un frame con solo `id:` (el de apertura) actualiza `lastEventId` sin despachar nada.
  private dispatch(): SseMessage | null {
    const hasData = this.data.length > 0;
    const message = { event: this.eventType || "message", data: this.data.join("\n"), id: this.lastEventId };
    this.data = [];
    this.eventType = "";
    return hasData ? message : null;
  }
}

export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** Math.max(0, attempt));
  const jitter = 1 + (random() * 2 - 1) * BACKOFF_JITTER;
  return Math.round(base * jitter);
}

class UnauthorizedError extends Error {}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const done = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", done);
      window.removeEventListener("online", done);
      resolve();
    };
    const timer = window.setTimeout(done, ms);
    signal.addEventListener("abort", done, { once: true });
    window.addEventListener("online", done, { once: true }); // de vuelta online: no esperar más
  });
}

async function readStream(
  { path, onEvent, signal }: ConnectSseOptions,
  lastEventId: string | null,
  onOpen: () => void,
): Promise<string | null> {
  const token = getAuthToken();
  if (!token) throw new UnauthorizedError("sin token");

  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  window.addEventListener("offline", abort);
  let watchdog = 0;
  const armWatchdog = () => {
    window.clearTimeout(watchdog);
    watchdog = window.setTimeout(() => {
      console.warn(`[sse] ${HEARTBEAT_TIMEOUT_MS / 1000} s sin datos: se corta la conexión`);
      abort();
    }, HEARTBEAT_TIMEOUT_MS);
  };

  const parser = new SseParser(lastEventId);
  try {
    const headers = new Headers({ Accept: "text/event-stream", Authorization: `Bearer ${token}` });
    if (lastEventId) headers.set("Last-Event-ID", lastEventId);
    armWatchdog();
    const response = await fetch(`${API_URL}${path}`, { headers, cache: "no-store", signal: controller.signal });
    if (response.status === 401) throw new UnauthorizedError("401");
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
    onOpen();

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      armWatchdog();
      for (const message of parser.feed(decoder.decode(value, { stream: true }))) onEvent(message);
    }
    console.warn("[sse] el servidor cerró el stream");
    return parser.lastEventId;
  } catch (error) {
    // Se conserva el último id recibido aunque la conexión haya caído a mitad.
    if (error && typeof error === "object") (error as { lastEventId?: string | null }).lastEventId = parser.lastEventId;
    throw error;
  } finally {
    window.clearTimeout(watchdog);
    signal.removeEventListener("abort", abort);
    window.removeEventListener("offline", abort);
  }
}

// Conecta y mantiene la conexión hasta `signal.abort()` o un 401.
export async function connectSse(options: ConnectSseOptions): Promise<void> {
  const { path, onStatus, signal } = options;
  let attempt = 0;
  let lastEventId: string | null = null;
  onStatus?.({ status: "connecting", attempt });

  while (!signal.aborted) {
    console.info(`[sse] conectando a ${path}`, lastEventId ? `(Last-Event-ID: ${lastEventId})` : "(conexión nueva)");
    try {
      lastEventId = await readStream(options, lastEventId, () => {
        console.info(`[sse] conectado${attempt ? ` tras ${attempt} reintento(s)` : ""}`);
        attempt = 0;
        onStatus?.({ status: "open", attempt });
      });
    } catch (error) {
      lastEventId = (error as { lastEventId?: string | null }).lastEventId ?? lastEventId;
      if (signal.aborted) break;
      if (error instanceof UnauthorizedError) {
        console.warn("[sse] 401: sesión caducada, no se reintenta");
        onStatus?.({ status: "unauthorized", attempt });
        return;
      }
      console.warn("[sse] conexión perdida:", error instanceof Error ? error.message : error);
    }
    if (signal.aborted) break;
    const delay = backoffDelay(attempt);
    attempt += 1;
    console.info(`[sse] reconectando en ${(delay / 1000).toFixed(1)} s (intento ${attempt})`);
    onStatus?.({ status: "reconnecting", attempt, retryInMs: delay });
    await sleep(delay, signal);
  }
  onStatus?.({ status: "closed", attempt });
}
