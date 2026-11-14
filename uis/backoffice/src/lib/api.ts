const API_URL = "/api/backend";

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
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
  headers.set("Content-Type", "application/json");
  const token = getAuthToken();
  if (protectedEndpoint && token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    if (response.status === 401 && protectedEndpoint) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("token");
      window.location.replace("/login");
    }
    let message = `Error ${response.status}: ${response.statusText}`;
    try {
      const error = await response.json();
      if (error.detail) {
        message = typeof error.detail === "string"
          ? error.detail
          : JSON.stringify(error.detail);
      }
    } catch {}
    throw new ApiError(response.status, message);
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