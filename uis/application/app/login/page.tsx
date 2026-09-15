"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { authApi } from "@/lib/api";
import { setAccessToken } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const result = await authApi.login(email, password);
      setAccessToken(result.access_token);
      router.push("/");
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "No se pudo iniciar sesión.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-[min(440px,92%)] items-center py-10">
      <section className="w-full rounded-3xl border border-cyan-100/10 bg-[linear-gradient(145deg,#10213a,#172842)] p-7 shadow-[0_20px_50px_rgba(7,13,25,0.45)] md:p-9">
        <p className="text-xs font-semibold tracking-[0.18em] text-cyan-300 uppercase">
          TrackFlow access
        </p>
        <h1
          className="mt-3 text-3xl font-semibold text-white"
          style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}
        >
          Iniciar sesión
        </h1>
        <p className="mt-2 text-sm text-slate-300">
          Accede al backoffice de operaciones.
        </p>
        <form className="mt-8 space-y-5" onSubmit={handleSubmit}>
          <label className="block text-sm text-slate-200">
            Email
            <input
              className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/30 px-4 py-3 text-white outline-none focus:border-cyan-300"
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="block text-sm text-slate-200">
            Contraseña
            <input
              className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/30 px-4 py-3 text-white outline-none focus:border-cyan-300"
              type="password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          {error && <p className="text-sm text-rose-300">{error}</p>}
          <button
            className="w-full rounded-xl bg-cyan-300 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={loading}
            type="submit"
          >
            {loading ? "Validando..." : "Entrar"}
          </button>
        </form>
        <Link
          className="mt-5 block text-center text-sm text-cyan-300 hover:text-cyan-200"
          href="/forgot-password"
        >
          ¿Olvidaste tu contraseña?
        </Link>
      </section>
    </main>
  );
}
