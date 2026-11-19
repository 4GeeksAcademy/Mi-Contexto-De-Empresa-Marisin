"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiError, login } from "@/lib/api";
import { rotateSession, track, withRequestId } from "@/lib/telemetry";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(email, password);
      rotateSession();
      try {
        sessionStorage.setItem("tf_telemetry_login_at", String(Date.now()));
      } catch {
        // Storage restrictions must not prevent login.
      }
      track("user_login_succeeded", {});
      router.replace("/inventory/orders/inbound");
    } catch (error) {
      const failure_reason = error instanceof ApiError
        ? error.status === 401 || error.status === 422 ? "invalid_credentials"
          : error.status === 403 ? "account_locked" : null
        : error instanceof TypeError ? "network_error" : null;
      if (failure_reason) {
        const report = () => track("user_login_failed", { failure_reason });
        if (error instanceof ApiError && error.requestId) withRequestId(error.requestId, report);
        else report();
      }
      setError(error instanceof Error ? error.message : "No se pudo iniciar sesion.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="max-w-md mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">TrackFlow Backoffice</h1>
      <h2 className="text-lg font-medium">Iniciar sesi&oacute;n</h2>
      {error && <p role="alert" className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-md">{error}</p>}
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="email" className="block text-sm font-medium mb-1">Email</label>
          <input id="email" type="email" autoComplete="username" required value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md" />
        </div>
        <div>
          <label htmlFor="password" className="block text-sm font-medium mb-1">Contrase&ntilde;a</label>
          <input id="password" type="password" autoComplete="current-password" required value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md" />
        </div>
        <button type="submit" disabled={loading}
          className="w-full bg-green-600 hover:bg-green-700 text-white font-medium py-2 px-4 rounded-md disabled:opacity-50">
          {loading ? "Accediendo..." : "Iniciar sesion"}
        </button>
      </form>
    </main>
  );
}