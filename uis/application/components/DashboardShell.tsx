import type { ReactNode } from "react";

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
      </header>
      <div className="mt-6 space-y-6">{children}</div>
    </div>
  );
}
