"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { authApi } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await authApi.forgotPassword(email);
      setSent(true);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo procesar la solicitud.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-[min(500px,92%)] items-center py-10">
      <section className="w-full rounded-3xl border border-cyan-100/10 bg-[linear-gradient(145deg,#10213a,#172842)] p-7 shadow-[0_20px_50px_rgba(7,13,25,0.45)] md:p-9">
        <p className="text-xs font-semibold tracking-[0.18em] text-cyan-300 uppercase">Account recovery</p>
        <h1 className="mt-3 text-3xl font-semibold text-white" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>Recupera tu contraseña</h1>
        <p className="mt-2 text-sm leading-6 text-slate-300">Introduce tu email corporativo y te enviaremos instrucciones para continuar.</p>
        {sent ? <p className="mt-7 rounded-xl border border-emerald-300/20 bg-emerald-300/10 p-4 text-sm leading-6 text-emerald-200">Si esa dirección está registrada, recibirás un correo con instrucciones para restablecer tu contraseña.</p> : <form className="mt-7 space-y-5" onSubmit={handleSubmit}><label className="block text-sm text-slate-200">Email<input className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/30 px-4 py-3 text-white outline-none focus:border-cyan-300" type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>{error && <p className="text-sm text-rose-300">{error}</p>}<button className="w-full rounded-xl bg-cyan-300 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-60" disabled={loading} type="submit">{loading ? "Enviando..." : "Enviar instrucciones"}</button></form>}
        <Link className="mt-6 block text-center text-sm text-cyan-300 hover:text-cyan-200" href="/login">Volver al inicio de sesión</Link>
      </section>
    </main>
  );
}