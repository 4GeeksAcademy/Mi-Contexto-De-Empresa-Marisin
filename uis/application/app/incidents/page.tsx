import Link from "next/link";

import { DashboardShell } from "@/components/DashboardShell";
import { IncidentWorkspace } from "@/components/incidents/IncidentWorkspace";

export default function IncidentsPage() {
  return <DashboardShell><div className="mb-4 flex justify-end"><Link href="/incidents/new" className="rounded-xl bg-[var(--accent)] px-4 py-2.5 font-semibold text-slate-950">Nueva incidencia</Link></div><IncidentWorkspace /></DashboardShell>;
}
