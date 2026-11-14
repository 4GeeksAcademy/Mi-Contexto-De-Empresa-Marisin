"use client";

import { useEffect, useState } from "react";
import {
  getIncidentSummary,
  incidentBranches,
  incidentOrigins,
  incidentStatuses,
  listIncidents,
  updateIncidentStatus,
  type Incident,
  type IncidentStatus,
  type IncidentSummary as IncidentSummaryData,
} from "@/lib/incidents";

export function IncidentWorkspace() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [summary, setSummary] = useState<IncidentSummaryData | null>(null);
  const [filters, setFilters] = useState({ status: "", origin: "", branch: "" });
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [summaryError, setSummaryError] = useState("");
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  async function loadIncidents() {
    setIsLoading(true);
    setErrorMessage("");
    try {
      setIncidents(await listIncidents(filters));
    } catch {
      setErrorMessage("No se pudo cargar el listado de incidencias.");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadSummary() {
    setSummaryError("");
    try {
      setSummary(await getIncidentSummary());
    } catch {
      setSummaryError("El resumen no está disponible ahora.");
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setIsLoading(true);
      setErrorMessage("");
      void listIncidents(filters)
        .then(setIncidents)
        .catch(() => setErrorMessage("No se pudo cargar el listado de incidencias."))
        .finally(() => setIsLoading(false));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [filters]);
  useEffect(() => {
    const timer = window.setTimeout(() => { void loadSummary(); }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function changeStatus(incident: Incident, status: IncidentStatus) {
    const previous = incidents;
    setUpdatingId(incident.id);
    setIncidents((current) => current.map((item) => item.id === incident.id ? { ...item, status } : item));
    try {
      const updated = await updateIncidentStatus(incident.id, status);
      setIncidents((current) => current.map((item) => item.id === incident.id ? updated : item));
      void loadSummary();
    } catch {
      setIncidents(previous);
      setErrorMessage("No se pudo actualizar el estado. Se ha restaurado el valor anterior.");
    } finally {
      setUpdatingId(null);
    }
  }

  return <div className="space-y-6">
    <section className="rounded-3xl border border-white/10 bg-[var(--panel)] p-5 shadow-xl shadow-black/25 md:p-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div><p className="text-xs tracking-[0.18em] text-cyan-300 uppercase">Control operativo</p><h2 className="mt-1 text-2xl font-semibold text-white">Incidencias centralizadas</h2></div>
        <div className="grid gap-2 sm:grid-cols-3">
          <Filter label="Estado" value={filters.status} options={incidentStatuses} onChange={(status) => setFilters({ ...filters, status })} />
          <Filter label="Origen" value={filters.origin} options={incidentOrigins} onChange={(origin) => setFilters({ ...filters, origin })} />
          <Filter label="Sede" value={filters.branch} options={incidentBranches} onChange={(branch) => setFilters({ ...filters, branch })} />
        </div>
      </div>
    </section>

    <IncidentSummary summary={summary} error={summaryError} />

    <section className="rounded-3xl border border-white/10 bg-[var(--panel)] p-5 shadow-xl shadow-black/25 md:p-6">
      <div className="flex items-center justify-between gap-3"><h2 className="text-xl font-semibold text-white">Listado</h2><button type="button" onClick={() => { void loadIncidents(); }} className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200">Reintentar</button></div>
      {isLoading ? <p className="mt-5 text-sm text-cyan-200">Cargando incidencias...</p> : null}
      {errorMessage ? <p role="alert" className="mt-5 text-sm text-rose-300">{errorMessage}</p> : null}
      {!isLoading && !errorMessage && incidents.length === 0 ? <p className="mt-5 rounded-xl border border-dashed border-slate-600 p-5 text-sm text-slate-300">No hay incidencias para los filtros seleccionados.</p> : null}
      {!isLoading && incidents.length > 0 ? <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead className="text-xs tracking-wide text-slate-400 uppercase"><tr><th className="pb-3">Incidencia</th><th className="pb-3">Categoría</th><th className="pb-3">Sede</th><th className="pb-3">Estado</th></tr></thead><tbody className="divide-y divide-white/10">{incidents.map((incident) => <tr key={incident.id}><td className="py-3 pr-4"><p className="font-semibold text-white">{incident.title}</p><p className="text-xs text-slate-400">{incident.origin} · {incident.id}</p></td><td className="py-3 pr-4 text-slate-300">{incident.category}</td><td className="py-3 pr-4 text-slate-300">{incident.branch}</td><td className="py-3"><select disabled={updatingId === incident.id || incident.status === "resolved" || incident.status === "discarded"} value={incident.status} onChange={(event) => void changeStatus(incident, event.target.value as IncidentStatus)} className="rounded-lg border border-slate-600 bg-[var(--panel-soft)] px-2 py-1 text-slate-100"><option value={incident.status}>{incident.status}</option>{allowedNextStatuses(incident.status).map((status) => <option key={status} value={status}>{status}</option>)}</select></td></tr>)}</tbody></table></div> : null}
    </section>
  </div>;
}

function allowedNextStatuses(status: IncidentStatus): IncidentStatus[] {
  if (status === "open") return ["in_progress", "discarded"];
  if (status === "in_progress") return ["resolved", "discarded"];
  return [];
}

function Filter({ label, value, options, onChange }: { label: string; value: string; options: readonly string[]; onChange: (value: string) => void }) {
  return <label className="text-xs text-slate-400">{label}<select value={value} onChange={(event) => onChange(event.target.value)} className="mt-1 block w-full rounded-lg border border-slate-600 bg-[var(--panel-soft)] px-2 py-1.5 text-sm text-slate-100"><option value="">Todos</option>{options.map((option) => <option key={option}>{option}</option>)}</select></label>;
}

function IncidentSummary({ summary, error }: { summary: IncidentSummaryData | null; error: string }) {
  if (error) return <section className="rounded-3xl border border-rose-300/20 bg-rose-300/10 p-5 text-sm text-rose-200">{error}</section>;
  if (!summary) return <section className="rounded-3xl border border-white/10 bg-[var(--panel)] p-5 text-sm text-cyan-200">Cargando resumen...</section>;
  return <section className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <MetricCard label="Total" value={summary.total} />
      {Object.entries(summary.by_status).map(([label, value]) => <MetricCard key={`status-${label}`} label={label} value={value} />)}
    </div>
    <div className="grid gap-4 lg:grid-cols-3">
      <MetricGroup title="Por categoría" values={summary.by_category} />
      <MetricGroup title="Por origen" values={summary.by_origin} />
      <MetricGroup title="Por sede" values={summary.by_branch} />
    </div>
  </section>;
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4"><p className="text-xs tracking-wide text-slate-400 uppercase">{label}</p><p className="mt-1 text-2xl font-semibold text-white">{value}</p></article>;
}

function MetricGroup({ title, values }: { title: string; values: Record<string, number> }) {
  return <article className="rounded-2xl border border-white/10 bg-[var(--panel)] p-4"><h3 className="text-sm font-semibold text-cyan-200">{title}</h3><dl className="mt-3 space-y-2">{Object.entries(values).map(([label, value]) => <div key={label} className="flex items-center justify-between gap-3 text-sm"><dt className="text-slate-300">{label}</dt><dd className="font-semibold text-white">{value}</dd></div>)}</dl></article>;
}
