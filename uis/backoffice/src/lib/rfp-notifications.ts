import { useCallback, useEffect, useRef, useState } from "react";
import type { RfpStatus, RfpTicketSummary } from "./rfp";
import { connectSse, type SseMessage, type SseStatusInfo } from "./sse";

// Notificaciones en tiempo real de RFPs nuevas (`GET /realtime/events`).
// Mismos nombres que el sistema de RFPs: `status` llega como "analizando",
// `ticket_id` es entero y `client_country` es "United States" o "Spain".
//
// Dedupe (nunca dos avisos para el mismo ticket): un `Set` de `ticket_id` ya
// notificados. El servidor ya manda un solo evento por ticket, pero tras un
// replay o un `resync` el cliente puede ver otra vez tickets que ya conocía.

export const REALTIME_EVENTS_PATH = "/realtime/events";
export const EVENT_RFP_TICKET_CREATED = "rfp_ticket_created";
export const EVENT_RESYNC = "resync";

export interface RfpTicketCreatedEvent {
  ticket_id: number;
  rfp_id: string;
  client_name: string | null;
  client_country: string | null;
  services_requested: string[];
  status: RfpStatus;
  created_at: string;
  stage: string | null;
  original_filename: string | null;
}

export interface ResyncEvent {
  reason: string;
}

export const COUNTRY_LABELS: Record<string, string> = {
  "United States": "EE. UU.",
  Spain: "España",
};

// Fila de la lista a partir del evento (sin pedir el ticket a la API).
export function summaryFromEvent(event: RfpTicketCreatedEvent): RfpTicketSummary {
  return {
    ticket_id: event.ticket_id,
    rfp_id: event.rfp_id,
    status: event.status,
    stage: event.stage ?? "",
    original_filename: event.original_filename ?? event.rfp_id,
    client_name: event.client_name,
    error_stage: null,
    ready_for_drafting: false,
    ready_for_approval: false,
    stale: false,
    created_at: event.created_at,
    updated_at: event.created_at,
  };
}

// Upsert por `ticket_id`: nunca dos filas para el mismo ticket. Si la fila ya
// existe (la trajo el polling o un refetch) manda la de la API, que es más
// reciente; del evento solo se completa lo que falte.
export function upsertTicket(list: RfpTicketSummary[], event: RfpTicketCreatedEvent): RfpTicketSummary[] {
  const index = list.findIndex((ticket) => ticket.ticket_id === event.ticket_id);
  if (index === -1) {
    return [summaryFromEvent(event), ...list].sort((a, b) => b.ticket_id - a.ticket_id);
  }
  const current = list[index];
  if (current.client_name) return list;
  const next = list.slice();
  next[index] = { ...current, client_name: event.client_name };
  return next;
}

function isTicketCreated(value: unknown): value is RfpTicketCreatedEvent {
  const event = value as RfpTicketCreatedEvent | null;
  return (
    typeof event === "object" && event !== null &&
    Number.isInteger(event.ticket_id) && typeof event.rfp_id === "string" && Array.isArray(event.services_requested)
  );
}

export interface UseRfpNotificationsOptions {
  // Solo para tickets aún no notificados en esta pestaña.
  onTicket: (event: RfpTicketCreatedEvent) => void;
  // El servidor no pudo reenviar lo perdido: pedir la lista una vez.
  onResync: (event: ResyncEvent) => void;
  enabled?: boolean;
}

export interface UseRfpNotifications {
  connection: SseStatusInfo;
  wasNotified: (ticketId: number) => boolean;
  markNotified: (ticketIds: Iterable<number>) => void;
}

export function useRfpNotifications({ onTicket, onResync, enabled = true }: UseRfpNotificationsOptions): UseRfpNotifications {
  const [connection, setConnection] = useState<SseStatusInfo>({ status: "connecting", attempt: 0 });
  const notified = useRef<Set<number>>(new Set());
  // Los callbacks cambian en cada render: se leen de refs para no reconectar.
  const handlers = useRef({ onTicket, onResync });
  useEffect(() => {
    handlers.current = { onTicket, onResync };
  });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const onEvent = (message: SseMessage) => {
      let payload: unknown;
      try {
        payload = JSON.parse(message.data);
      } catch {
        console.warn("[sse] data no es JSON:", message.event, message.data);
        return;
      }
      if (message.event === EVENT_RFP_TICKET_CREATED && isTicketCreated(payload)) {
        if (notified.current.has(payload.ticket_id)) {
          console.info(`[sse] ticket #${payload.ticket_id} ya notificado: se ignora`);
          return;
        }
        notified.current.add(payload.ticket_id);
        handlers.current.onTicket(payload);
      } else if (message.event === EVENT_RESYNC) {
        console.info("[sse] resync:", (payload as ResyncEvent)?.reason);
        handlers.current.onResync(payload as ResyncEvent);
      }
    };
    void connectSse({ path: REALTIME_EVENTS_PATH, onEvent, onStatus: setConnection, signal: controller.signal });
    return () => controller.abort();
  }, [enabled]);

  const wasNotified = useCallback((ticketId: number) => notified.current.has(ticketId), []);
  const markNotified = useCallback((ticketIds: Iterable<number>) => {
    for (const ticketId of ticketIds) notified.current.add(ticketId);
  }, []);

  return { connection, wasNotified, markNotified };
}
