// Por defecto usamos el proxy same-origin de next.config.ts: funciona en local y en
// entornos remotos (Codespaces) sin depender de la URL pública del puerto 8000 ni de CORS.
const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/backend").replace(/\/$/, "");

type ApiOptions = RequestInit & { token?: string };

export async function apiRequest<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.detail ?? "No se pudo completar la solicitud.");
  }
  return body as T;
}

export const authApi = {
  login: (email: string, password: string) =>
    apiRequest<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  forgotPassword: (email: string) =>
    apiRequest<{ message: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  resetPassword: (token: string, newPassword: string) =>
    apiRequest<{ message: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password: newPassword }),
    }),
  changePassword: (token: string, currentPassword: string, newPassword: string) =>
    apiRequest<{ message: string }>("/auth/change-password", {
      method: "POST",
      token,
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    }),
};