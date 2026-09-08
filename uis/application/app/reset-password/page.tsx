"use client";

import Link from "next/link";
import { FormEvent, Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { authApi } from "@/lib/api";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState(token ? "" : "El enlace de recuperación no es válido.");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    if (password.length < 8) {
      setError("La contraseña debe tener al menos 8 caracteres.");
      return;
    }
    if (password !== confirmation) {
      setError("Las contraseñas no coinciden.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      await authApi.resetPassword(token, password);
      router.replace("/login");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo restablecer la contraseña.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="w-full rounded-3xl border border-cyan-100/10 bg-[linear-gradient(145deg,#10213a,#172842)] p-7 shadow-[0_20px_50px_rgba(7,13,25,0.45)] md:p-9">
      <p className="text-xs font-semibold tracking-[0.18em] text-cyan-300 uppercase">Account recovery</p>
      <h1 className="mt-3 text-3xl font-semibold text-white" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>Crea una nueva contraseña</h1>
      <p className="mt-2 text-sm leading-6 text-slate-300">Elige una contraseña segura para volver a acceder a TrackFlow.</p>
      <form className="mt-7 space-y-5" onSubmit={handleSubmit}>
        <label className="block text-sm text-slate-200">Nueva contraseña<input className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/30 px-4 py-3 text-white outline-none focus:border-cyan-300" type="password" minLength={8} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <label className="block text-sm text-slate-200">Confirmar contraseña<input className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/30 px-4 py-3 text-white outline-none focus:border-cyan-300" type="password" minLength={8} required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
        {error && <p className="text-sm text-rose-300">{error}</p>}
        <button className="w-full rounded-xl bg-cyan-300 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-60" disabled={loading || !token} type="submit">{loading ? "Guardando..." : "Restablecer contraseña"}</button>
      </form>
      <Link className="mt-6 block text-center text-sm text-cyan-300 hover:text-cyan-200" href="/login">Volver al inicio de sesión</Link>
    </section>
  );
}

export default function ResetPasswordPage() {
  return <main className="mx-auto flex min-h-screen w-[min(500px,92%)] items-center py-10"><Suspense fallback={<p className="text-sm text-slate-300">Cargando enlace...</p>}><ResetPasswordForm /></Suspense></main>;
}