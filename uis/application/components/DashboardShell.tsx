import type { ReactNode } from "react";
import Link from "next/link";

export function DashboardShell({ children }: { children: ReactNode }) {
  return (
    <div className="dashboard-shell py-8 md:py-10">
      <header className="rounded-3xl border border-cyan-100/10 bg-[linear-gradient(135deg,#10213a_0%,#1d2f4f_100%)] p-6 shadow-[0_20px_50px_rgba(7,13,25,0.45)] md:p-8">
        <p className="text-xs font-semibold tracking-[0.18em] text-cyan-300 uppercase">TrackFlow Internal Console</p>
        <h1
          className="mt-2 text-3xl font-semibold text-white md:text-4xl"
          style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}
        >
          Backoffice de Operaciones y Talento
        </h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-300 md:text-base">
          Vista unificada para coordinacion interna entre operaciones logisticas, experiencia del cliente y seguimiento del pipeline de talento.
        </p>
        <nav className="mt-5 flex flex-wrap gap-2 text-sm" aria-label="Navegacion principal">
          <Link href="/" className="rounded-lg border border-white/15 px-3 py-2 text-slate-200 hover:border-cyan-300/60">Inicio</Link>
          <Link href="/incidents" className="rounded-lg border border-cyan-300/40 bg-cyan-300/10 px-3 py-2 text-cyan-100 hover:bg-cyan-300/20">Incidencias</Link>
        </nav>
      </header>
      <div className="mt-6 space-y-6">{children}</div>
    </div>
  );
}
