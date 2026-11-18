import { getAuthToken } from "./api";
import { sanitizeErrorMessage } from "./telemetry-mappers";

const SCHEMA_VERSION = "1.0.0";
const BATCH_SIZE = 20;
const FLUSH_INTERVAL_MS = 10_000;
const THROTTLE_WINDOW_MS = 60_000;
const THROTTLE_STORAGE_PREFIX = "tf_telemetry_throttle_";

type TelemetryEventType =
  | "inbound_order_created"
  | "outbound_order_created"
  | "stock_threshold_triggered"
  | "direct_stock_edit_rejected"
  | "inventory_discrepancy_detected"
  | "inbound_order_validation_failed"
  | "outbound_order_validation_failed"
  | "order_form_started"
  | "order_form_abandoned"
  | "stock_threshold_cleared"
  | "user_login_succeeded"
  | "user_login_failed"
  | "session_expired"
  | "user_logged_out"
  | "route_access_denied"
  | "page_viewed"
  | "api_latency_recorded"
  | "web_vital_recorded"
  | "frontend_error_captured"
  | "api_request_failed";

type TelemetryEnvelope = {
  eventId: string;
  timestamp: string;
  sessionId: string;
  userId: string | null;
  event_type: TelemetryEventType;
  schemaVersion: string;
  requestId: string;
  properties: Record<string, unknown>;
};

type ThrottleState = {
  pageViews: Record<string, number>;
  errorFingerprints: Record<string, number>;
  errorTimestamps: number[];
  loginFailureTimestamps: number[];
};

type ActiveBatch = {
  events: string[];
  beaconed: boolean;
};

const PROPERTY_ALLOWLISTS: Record<TelemetryEventType, readonly string[]> = {
  inbound_order_created: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "order_id",
  ],
  outbound_order_created: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "order_id", "exit_type",
  ],
  stock_threshold_triggered: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "min_threshold", "threshold_source", "trigger_order_id",
  ],
  direct_stock_edit_rejected: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "rejection_reason", "attempted_delta",
  ],
  inventory_discrepancy_detected: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "system_quantity", "counted_quantity", "detection_source",
  ],
  inbound_order_validation_failed: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "failure_reason", "validation_source",
  ],
  outbound_order_validation_failed: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "failure_reason", "validation_source",
  ],
  order_form_started: ["order_kind"],
  order_form_abandoned: [
    "order_kind", "last_field_touched", "fields_completed", "time_in_form_ms",
  ],
  stock_threshold_cleared: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "min_threshold", "threshold_source", "trigger_order_id",
  ],
  user_login_succeeded: [],
  user_login_failed: ["failure_reason"],
  session_expired: ["route", "api_endpoint"],
  user_logged_out: ["session_duration_ms"],
  route_access_denied: ["route", "reason", "api_endpoint"],
  page_viewed: ["route"],
  api_latency_recorded: [
    "api_endpoint", "duration_ms", "http_method", "status_code", "sample_rate",
  ],
  web_vital_recorded: ["route", "metric_name", "metric_value"],
  frontend_error_captured: [
    "route", "message", "stack_frames", "error_source", "error_fingerprint",
  ],
  api_request_failed: ["api_endpoint", "failure_reason", "status_code"],
};

const REQUIRED_PROPERTIES: Record<TelemetryEventType, readonly string[]> = {
  inbound_order_created: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "order_id",
  ],
  outbound_order_created: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "order_id", "exit_type",
  ],
  stock_threshold_triggered: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "min_threshold", "threshold_source", "trigger_order_id",
  ],
  direct_stock_edit_rejected: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "rejection_reason",
  ],
  inventory_discrepancy_detected: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "system_quantity", "counted_quantity", "detection_source",
  ],
  inbound_order_validation_failed: [
    "warehouse", "client_id", "product_id", "product_category", "country", "failure_reason", "validation_source",
  ],
  outbound_order_validation_failed: [
    "warehouse", "client_id", "product_id", "product_category", "country", "failure_reason", "validation_source",
  ],
  order_form_started: ["order_kind"],
  order_form_abandoned: [
    "order_kind", "last_field_touched", "fields_completed", "time_in_form_ms",
  ],
  stock_threshold_cleared: [
    "warehouse", "client_id", "product_id", "product_category", "quantity", "country", "min_threshold", "threshold_source", "trigger_order_id",
  ],
  user_login_succeeded: [],
  user_login_failed: ["failure_reason"],
  session_expired: ["route", "api_endpoint"],
  user_logged_out: ["session_duration_ms"],
  route_access_denied: ["route", "reason"],
  page_viewed: ["route"],
  api_latency_recorded: [
    "api_endpoint", "duration_ms", "http_method", "status_code", "sample_rate",
  ],
  web_vital_recorded: ["route", "metric_name", "metric_value"],
  frontend_error_captured: [
    "route", "message", "error_source", "error_fingerprint",
  ],
  api_request_failed: ["api_endpoint", "failure_reason"],
};

let eventQueue: string[] = [];
let flushTimer: number | null = null;
let listenersRegistered = false;
let inFlight: ActiveBatch | null = null;
let beaconFlushInProgress = false;
let warnedMissingEndpoint = false;
let currentRequestId: string | null = null;
let memorySessionId: string | null = null;
const memoryThrottleStates = new Map<string, ThrottleState>();

function randomId(): string {
  return globalThis.crypto.randomUUID();
}

function getSessionId(): string {
  try {
    const stored = window.sessionStorage.getItem("tf_telemetry_session");
    if (stored) {
      memorySessionId = stored;
      return stored;
    }
    const sessionId = memorySessionId ?? randomId();
    window.sessionStorage.setItem("tf_telemetry_session", sessionId);
    memorySessionId = sessionId;
    return sessionId;
  } catch {
    memorySessionId ??= randomId();
    return memorySessionId;
  }
}

function getUserIdFromToken(): string | null {
  try {
    const token = getAuthToken();
    const payload = token?.split(".")[1];
    if (!payload) return null;
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    const binary = atob(padded);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const decoded = new TextDecoder().decode(bytes);
    const subject: unknown = JSON.parse(decoded).sub;
    return typeof subject === "string" && subject.trim() ? subject : null;
  } catch {
    return null;
  }
}

function readThrottleState(sessionId: string): ThrottleState {
  const memoryState = memoryThrottleStates.get(sessionId);
  try {
    const serialized = window.sessionStorage.getItem(
      `${THROTTLE_STORAGE_PREFIX}${sessionId}`,
    );
    if (serialized) {
      const state = JSON.parse(serialized) as Partial<ThrottleState>;
      if (
        state.pageViews &&
        state.errorFingerprints &&
        Array.isArray(state.errorTimestamps) &&
        Array.isArray(state.loginFailureTimestamps)
      ) {
        return state as ThrottleState;
      }
    }
  } catch {
    return memoryState ?? {
      pageViews: {},
      errorFingerprints: {},
      errorTimestamps: [],
      loginFailureTimestamps: [],
    };
  }
  return memoryState ?? {
    pageViews: {},
    errorFingerprints: {},
    errorTimestamps: [],
    loginFailureTimestamps: [],
  };
}

function writeThrottleState(sessionId: string, state: ThrottleState): void {
  memoryThrottleStates.set(sessionId, state);
  try {
    window.sessionStorage.setItem(
      `${THROTTLE_STORAGE_PREFIX}${sessionId}`,
      JSON.stringify(state),
    );
  } catch {
    return;
  }
}

function isThrottled(
  eventType: TelemetryEventType,
  properties: Record<string, unknown>,
  sessionId: string,
): boolean {
  const now = Date.now();
  const state = readThrottleState(sessionId);
  state.errorTimestamps = state.errorTimestamps.filter(
    (timestamp) => now - timestamp < THROTTLE_WINDOW_MS,
  );
  state.loginFailureTimestamps = state.loginFailureTimestamps.filter(
    (timestamp) => now - timestamp < THROTTLE_WINDOW_MS,
  );
  for (const [fingerprint, timestamp] of Object.entries(state.errorFingerprints)) {
    if (now - timestamp >= THROTTLE_WINDOW_MS) {
      delete state.errorFingerprints[fingerprint];
    }
  }

  if (eventType === "page_viewed") {
    const route = properties.route;
    if (typeof route !== "string") return true;
    const previous = state.pageViews[route];
    if (previous !== undefined && now - previous < 1_000) {
      writeThrottleState(sessionId, state);
      return true;
    }
    state.pageViews[route] = now;
  } else if (eventType === "frontend_error_captured") {
    const fingerprint = properties.error_fingerprint;
    if (typeof fingerprint !== "string" || !fingerprint) return true;
    const previous = state.errorFingerprints[fingerprint];
    if (
      (previous !== undefined && now - previous < THROTTLE_WINDOW_MS) ||
      state.errorTimestamps.length >= 10
    ) {
      writeThrottleState(sessionId, state);
      return true;
    }
    state.errorFingerprints[fingerprint] = now;
    state.errorTimestamps.push(now);
  } else if (eventType === "user_login_failed") {
    if (state.loginFailureTimestamps.length >= 20) {
      writeThrottleState(sessionId, state);
      return true;
    }
    state.loginFailureTimestamps.push(now);
  }

  writeThrottleState(sessionId, state);
  return false;
}

function telemetryEndpoint(): string | undefined {
  return process.env.NEXT_PUBLIC_TELEMETRY_ENDPOINT;
}

function warnMissingEndpoint(): void {
  if (warnedMissingEndpoint) return;
  warnedMissingEndpoint = true;
  console.warn("Telemetry is disabled because NEXT_PUBLIC_TELEMETRY_ENDPOINT is not set.");
}

function ensureRuntime(): void {
  if (!flushTimer) {
    flushTimer = window.setInterval(() => {
      void flushBatch();
    }, FLUSH_INTERVAL_MS);
  }
  if (listenersRegistered) return;
  listenersRegistered = true;
  const flushOnHide = () => {
    if (document.visibilityState === "hidden") flushBeacon();
  };
  document.addEventListener("visibilitychange", flushOnHide);
  window.addEventListener("pagehide", flushBeacon);
}

function enqueue(event: TelemetryEnvelope): void {
  const serialized = JSON.stringify(event);
  if (!serialized) return;
  eventQueue.push(serialized);
  if (eventQueue.length >= BATCH_SIZE) void flushBatch();
}

export function track(
  eventType: TelemetryEventType,
  properties: Record<string, unknown>,
): void {
  try {
    if (typeof window === "undefined") return;
    if (!Object.prototype.hasOwnProperty.call(PROPERTY_ALLOWLISTS, eventType)) return;

    const allowedProperties: Record<string, unknown> = {};
    for (const key of PROPERTY_ALLOWLISTS[eventType]) {
      const value = properties[key];
      if (value !== undefined) {
        allowedProperties[key] = eventType === "frontend_error_captured" && key === "message" && typeof value === "string"
          ? sanitizeErrorMessage(value)
          : value;
      }
    }
    for (const key of REQUIRED_PROPERTIES[eventType]) {
      const value = allowedProperties[key];
      if (
        value === undefined ||
        value === null ||
        (typeof value === "string" && !value.trim()) ||
        (typeof value === "number" && !Number.isFinite(value))
      ) {
        return;
      }
    }

    const sessionId = getSessionId();
    let userId = getUserIdFromToken();
    if (
      eventType === "user_login_failed" ||
      (eventType === "page_viewed" && allowedProperties.route === "/login")
    ) {
      userId = null;
    }
    if (
      userId === null &&
      !(
        eventType === "user_login_failed" ||
        (eventType === "page_viewed" && allowedProperties.route === "/login") ||
        (eventType === "route_access_denied" && allowedProperties.reason === "no_session")
      )
    ) {
      return;
    }
    if (isThrottled(eventType, allowedProperties, sessionId)) return;

    enqueue({
      eventId: randomId(),
      timestamp: new Date().toISOString(),
      sessionId,
      userId,
      event_type: eventType,
      schemaVersion: SCHEMA_VERSION,
      requestId: currentRequestId ?? randomId(),
      properties: allowedProperties,
    });
    ensureRuntime();
  } catch {
    return;
  }
}

function removeEvents(events: string[]): void {
  const sent = new Set(events);
  eventQueue = eventQueue.filter((event) => !sent.has(event));
}

function markBatchSent(events: string[], activeBatch: ActiveBatch | null): void {
  removeEvents(events);
  if (activeBatch && events.some((event) => activeBatch.events.includes(event))) {
    activeBatch.beaconed = true;
    if (inFlight === activeBatch) inFlight = null;
  }
}

function completeBatch(batch: ActiveBatch): void {
  if (inFlight === batch) inFlight = null;
  if (eventQueue.length >= BATCH_SIZE) void flushBatch();
}

async function flushBatch(): Promise<void> {
  if (inFlight || beaconFlushInProgress || eventQueue.length === 0) return;
  const endpoint = telemetryEndpoint();
  if (!endpoint) {
    warnMissingEndpoint();
    eventQueue = [];
    return;
  }

  const batch: ActiveBatch = {
    events: eventQueue.splice(0, BATCH_SIZE),
    beaconed: false,
  };
  inFlight = batch;

  try {
    for (let attempt = 0; attempt <= 3; attempt += 1) {
      if (batch.beaconed) return;
      if (attempt > 0) {
        await new Promise((resolve) => window.setTimeout(resolve, 1_000 * 2 ** (attempt - 1)));
        if (batch.beaconed) return;
      }

      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ events: batch.events.map((event) => JSON.parse(event)) }),
          keepalive: true,
        });
        if (response.ok) {
          completeBatch(batch);
          return;
        }
      } catch {
        if (attempt === 3) break;
      }
    }
    console.debug("Telemetry batch discarded after retries.");
  } finally {
    completeBatch(batch);
  }
}

function flushBeacon(): void {
  if (typeof window === "undefined" || beaconFlushInProgress) return;
  const endpoint = telemetryEndpoint();
  if (!endpoint) {
    if (eventQueue.length > 0 || inFlight) warnMissingEndpoint();
    eventQueue = [];
    if (inFlight) {
      inFlight.beaconed = true;
      inFlight = null;
    }
    return;
  }

  const activeBatch = inFlight;
  const events = [
    ...(activeBatch?.events ?? []),
    ...eventQueue,
  ];
  if (events.length === 0) return;

  const fallbackRequests: Promise<void>[] = [];
  for (let offset = 0; offset < events.length; offset += BATCH_SIZE) {
    const batchEvents = events.slice(offset, offset + BATCH_SIZE);
    const payload = JSON.stringify({
      events: batchEvents.map((event) => JSON.parse(event)),
    });
    const blob = new Blob([payload], { type: "application/json" });
    let accepted = false;
    try {
      accepted = window.navigator.sendBeacon(endpoint, blob);
    } catch {
      accepted = false;
    }

    if (accepted) {
      markBatchSent(batchEvents, activeBatch);
      continue;
    }

    fallbackRequests.push(
      fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: payload,
        keepalive: true,
      }).then((response) => {
        if (response.ok) markBatchSent(batchEvents, activeBatch);
      }).catch(() => undefined),
    );
  }

  if (fallbackRequests.length === 0) return;
  beaconFlushInProgress = true;
  void Promise.all(fallbackRequests)
    .finally(() => {
      beaconFlushInProgress = false;
      if (eventQueue.length >= BATCH_SIZE) void flushBatch();
    });
}

export function withRequestId<T>(id: string, fn: () => T): T {
  const previous = currentRequestId;
  currentRequestId = id;
  try {
    return fn();
  } finally {
    currentRequestId = previous;
  }
}

export function rotateSession(): void {
  try {
    memorySessionId = randomId();
    window.sessionStorage.setItem("tf_telemetry_session", memorySessionId);
  } catch {
    return;
  }
}

export { SCHEMA_VERSION };
