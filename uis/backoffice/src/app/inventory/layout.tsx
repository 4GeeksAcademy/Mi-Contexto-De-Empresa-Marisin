"use client";

import { useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { fetchWithAuth, getAuthToken } from "@/lib/api";

export default function InventoryLayout({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [authenticated, setAuthenticated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getAuthToken()) {
      router.replace("/login");
      return;
    }
    let active = true;
    fetchWithAuth("/auth/me")
      .then(() => { if (active) setAuthenticated(true); })
      .catch((error: unknown) => {
        if (active) setError(error instanceof Error ? error.message : "No se pudo verificar la sesion.");
      });
    return () => { active = false; };
  }, [router]);

  if (error) {
    return (
      <main className="max-w-2xl mx-auto p-6 space-y-4">
        <p role="alert" className="text-red-700">{error}</p>
        <Link href="/login" className="underline">Iniciar sesi&oacute;n</Link>
      </main>
    );
  }
  if (!authenticated) return <p role="status" className="p-6">Verificando sesi&oacute;n...</p>;
  return children;
}