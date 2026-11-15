import Link from "next/link";

import { DashboardShell } from "@/components/DashboardShell";
import { IncidentForm } from "@/components/incidents/IncidentForm";

export default function NewIncidentPage() {
  return <DashboardShell><div className="mb-4 flex items-center justify-between gap-3"><div><p className="text-xs tracking-[0.18em] text-cyan-300 uppercase">Registro</p><h2 className="mt-1 text-2xl font-semibold text-white">Nueva incidencia</h2></div><Link href="/incidents" className="rounded-lg border border-slate-600 px-3 py-2 text-sm text-slate-200">Volver al listado</Link></div><IncidentForm /></DashboardShell>;
}
