import { track, withRequestId } from "./telemetry";
import { toRouteTemplate } from "./telemetry-mappers";

const API_URL = "/api/backend";
const telemetryMethods = new Set(["GET", "POST", "PUT", "PATCH", "DELETE"]);

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly requestId: string | undefined,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token") || localStorage.getItem("token");
}

export async function fetchWithAuth(
  endpoint: string,
  options: RequestInit = {},
  protectedEndpoint = true,
) {
  const headers = new Headers(options.headers);
  // JSON por defecto; una subida binaria (p. ej. el PDF de una RFP) trae su propio Content-Type.
  if (!headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const requestId = globalThis.crypto?.randomUUID?.();
  if (requestId) headers.set("X-Request-ID", requestId);
  const token = getAuthToken();
  if (protectedEndpoint && token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const api_endpoint = toRouteTemplate(endpoint);
  const route = typeof window === "undefined"
    ? null
    : toRouteTemplate(window.location.pathname);
  function report(type: Parameters<typeof track>[0], properties: Parameters<typeof track>[1]) {
    if (requestId) withRequestId(requestId, () => track(type, properties));
  }

  const startedAt = performance.now();
  let response: Response;
  try {
    response = await fetch(`${API_URL}${endpoint}`, {
      ...options,
      headers,
      cache: "no-store",
    });
  } catch (error) {
    report("api_request_failed", { api_endpoint, failure_reason: "network_error" });
    throw error;
  }

  const duration = performance.now() - startedAt;
  const status_code = response.status;
  const http_method = (options.method ?? "GET").toUpperCase();
  const sample_rate = status_code >= 400 || duration > 1000 ? 1 : 0.2;
  if (telemetryMethods.has(http_method) && (sample_rate === 1 || Math.random() < sample_rate)) {
    report("api_latency_recorded", {
      api_endpoint,
      http_method,
      status_code,
      duration_ms: Math.round(duration),
      sample_rate,
    });
  }
  if (status_code >= 500 && status_code <= 599) {
    report("api_request_failed", { api_endpoint, failure_reason: "http_5xx", status_code });
  }

  if (!response.ok) {
    if (status_code === 401 && protectedEndpoint && route !== null) {
      if (token) report("session_expired", { route, api_endpoint });
      localStorage.removeItem("access_token");
      localStorage.removeItem("token");
      window.location.replace("/login");
    }
    let message = `Error ${status_code}: ${response.statusText}`;
    let inactiveUser = false;
    try {
      const error = await response.json();
      inactiveUser = error?.detail === "Inactive user";
      if (error.detail) {
        message = typeof error.detail === "string"
          ? error.detail
          : JSON.stringify(error.detail);
      }
    } catch {}
    if (status_code === 403 && route !== null) {
      report("route_access_denied", {
        route,
        api_endpoint,
        reason: inactiveUser ? "inactive_user" : "insufficient_permissions",
      });
    }
    throw new ApiError(status_code, message, requestId);
  }

  return response.json();
}

export async function login(email: string, password: string): Promise<void> {
  const data = await fetchWithAuth("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  }, false);
  if (typeof data.access_token !== "string" || !data.access_token) {
    throw new Error("La API no ha devuelto un token de acceso valido.");
  }
  localStorage.removeItem("token");
  localStorage.setItem("access_token", data.access_token);
}