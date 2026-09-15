"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { AuthGuard } from "@/components/AuthGuard";
import { authApi } from "@/lib/api";
import { getAccessToken } from "@/lib/auth";

export default function ChangePasswordPage() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (newPassword.length < 8) {
      setError("La nueva contraseña debe tener al menos 8 caracteres.");
      return;
    }
    if (newPassword !== confirmation) {
      setError("Las contraseñas nuevas no coinciden.");
      return;
    }
    const token = getAccessToken();
    if (!token) return;
    setLoading(true);
    setError("");
    setMessage("");
    try {
      const result = await authApi.changePassword(token, currentPassword, newPassword);
      setMessage(result.message);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo cambiar la contraseña.");
    } finally {
      setLoading(false);
    }
  }

  return <AuthGuard><main className="mx-auto flex min-h-screen w-[min(500px,92%)] items-center py-10"><section className="w-full rounded-3xl border border-cyan-100/10 bg-[linear-gradient(145deg,#10213a,#172842)] p-7 shadow-[0_20px_50px_rgba(7,13,25,0.45)] md:p-9"><p className="text-xs font-semibold tracking-[0.18em] text-cyan-300 uppercase">Account security</p><h1 className="mt-3 text-3xl font-semibold text-white" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>Cambiar contraseña</h1><p className="mt-2 text-sm leading-6 text-slate-300">Confirma tu contraseña actual antes de guardar una nueva.</p><form className="mt-7 space-y-5" onSubmit={handleSubmit}><label className="block text-sm text-slate-200">Contraseña actual<input className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/30 px-4 py-3 text-white outline-none focus:border-cyan-300" type="password" required value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} /></label><label className="block text-sm text-slate-200">Nueva contraseña<input className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/30 px-4 py-3 text-white outline-none focus:border-cyan-300" type="password" minLength={8} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} /></label><label className="block text-sm text-slate-200">Confirmar contraseña<input className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/30 px-4 py-3 text-white outline-none focus:border-cyan-300" type="password" minLength={8} required value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>{error && <p className="text-sm text-rose-300">{error}</p>}{message && <p className="rounded-xl border border-emerald-300/20 bg-emerald-300/10 p-4 text-sm text-emerald-200">{message}</p>}<button className="w-full rounded-xl bg-cyan-300 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-60" disabled={loading} type="submit">{loading ? "Guardando..." : "Guardar contraseña"}</button></form><Link className="mt-6 block text-center text-sm text-cyan-300 hover:text-cyan-200" href="/">Volver al backoffice</Link></section></main></AuthGuard>;
}