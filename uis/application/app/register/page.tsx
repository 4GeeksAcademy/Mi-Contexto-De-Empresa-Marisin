"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

type RegisterForm = {
  email: string;
  password: string;
  name: string;
  phone: string;
  address: string;
};

type ApiError = {
  detail?: string;
};

type LoginResponse = {
  access_token?: string;
};

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  "/api";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState<RegisterForm>({
    email: "",
    password: "",
    name: "",
    phone: "",
    address: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function updateField(field: keyof RegisterForm, value: string) {
    setForm((currentForm) => ({ ...currentForm, [field]: value }));
  }

  async function getErrorMessage(response: Response, fallback: string) {
    const data = (await response.json().catch(() => null)) as ApiError | null;
    return data?.detail ?? fallback;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);

    const registrationData = {
      email: form.email,
      password: form.password,
      ...(form.name && { name: form.name }),
      ...(form.phone && { phone: form.phone }),
      ...(form.address && { address: form.address }),
    };

    try {
      const registrationResponse = await fetch(`${API_URL}/users`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(registrationData),
      });

      if (!registrationResponse.ok) {
        throw new Error(
          await getErrorMessage(
            registrationResponse,
            "No se pudo crear la cuenta. Revisa los datos e inténtalo de nuevo.",
          ),
        );
      }

      const loginResponse = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email: form.email, password: form.password }),
      });

      if (!loginResponse.ok) {
        throw new Error(
          await getErrorMessage(
            loginResponse,
            "La cuenta se creó, pero no se pudo iniciar sesión automáticamente.",
          ),
        );
      }

      const loginData = (await loginResponse.json()) as LoginResponse;
      if (!loginData.access_token) {
        throw new Error("La respuesta del servidor no contiene un token válido.");
      }

      localStorage.setItem("token", loginData.access_token);
      router.push("/suppliers");
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "No se pudo conectar con el servidor.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6 py-12">
      <section className="w-full max-w-lg rounded-2xl border border-slate-800 bg-slate-900 p-8 shadow-2xl shadow-slate-950/50">
        <div className="mb-8">
          <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-cyan-400">
            TrackFlow
          </p>
          <h1 className="text-3xl font-bold tracking-tight text-white">
            Crea tu cuenta
          </h1>
          <p className="mt-2 text-sm text-slate-400">
            Regístrate para gestionar tu directorio de proveedores.
          </p>
        </div>

        <form className="space-y-5" onSubmit={handleSubmit}>
          <div>
            <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="email">
              Email
            </label>
            <input
              autoComplete="email"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
              id="email"
              onChange={(event) => updateField("email", event.target.value)}
              placeholder="tu@email.com"
              required
              type="email"
              value={form.email}
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="password">
              Contraseña
            </label>
            <input
              autoComplete="new-password"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
              id="password"
              minLength={8}
              onChange={(event) => updateField("password", event.target.value)}
              placeholder="Mínimo 8 caracteres"
              required
              type="password"
              value={form.password}
            />
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="name">
                Nombre <span className="text-slate-500">(opcional)</span>
              </label>
              <input
                autoComplete="name"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
                id="name"
                onChange={(event) => updateField("name", event.target.value)}
                placeholder="Tu nombre"
                type="text"
                value={form.name}
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="phone">
                Teléfono <span className="text-slate-500">(opcional)</span>
              </label>
              <input
                autoComplete="tel"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
                id="phone"
                onChange={(event) => updateField("phone", event.target.value)}
                placeholder="+34 600 000 000"
                type="tel"
                value={form.phone}
              />
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="address">
              Dirección <span className="text-slate-500">(opcional)</span>
            </label>
            <input
              autoComplete="street-address"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
              id="address"
              onChange={(event) => updateField("address", event.target.value)}
              placeholder="Calle, ciudad"
              type="text"
              value={form.address}
            />
          </div>

          {error && (
            <p
              aria-live="polite"
              className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
              role="alert"
            >
              {error}
            </p>
          )}

          <button
            className="flex w-full items-center justify-center rounded-lg bg-cyan-400 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={loading}
            type="submit"
          >
            {loading ? "Creando cuenta..." : "Crear cuenta"}
          </button>
        </form>
      </section>
    </main>
  );
}
