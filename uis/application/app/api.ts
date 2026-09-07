const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api";

export class UnauthorizedError extends Error {
  constructor() {
    super("Tu sesión ha caducado. Inicia sesión de nuevo.");
  }
}

export function clearSessionAndRedirect() {
  localStorage.removeItem("token");
  window.location.replace("/login");
}

export async function protectedFetch(path: string, options: RequestInit = {}) {
  const token = localStorage.getItem("token");
  if (!token) {
    clearSessionAndRedirect();
    throw new UnauthorizedError();
  }

  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    clearSessionAndRedirect();
    throw new UnauthorizedError();
  }

  return response;
}