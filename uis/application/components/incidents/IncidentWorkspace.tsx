"use client";

import { useCallback, useEffect, useState } from "react";
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

type AsyncStatus = "loading" | "success" | "error";

const listErrorMessage = "No se pudo cargar el listado de incidencias. Revisa la conexión y vuelve a intentarlo.";
const summaryErrorMessage = "El resumen no está disponible ahora. Puedes reintentar sin perder el listado.";
const statusErrorMessage = "No se pudo actualizar el estado. Se ha restaurado el valor anterior.";

export function IncidentWorkspace() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [summary, setSummary] = useState<IncidentSummaryData | null>(null);
  const [filters, setFilters] = useState({ status: "", origin: "", branch: "" });
  const [listStatus, setListStatus] = useState<AsyncStatus>("loading");
  const [summaryStatus, setSummaryStatus] = useState<AsyncStatus>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [summaryError, setSummaryError] = useState("");
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const loadIncidents = useCallback(async () => {
    setListStatus("loading");
    setErrorMessage("");
    try {
      const data = await listIncidents(filters);
      setIncidents(Array.isArray(data) ? data : []);
      setListStatus("success");
    } catch {
      setErrorMessage(listErrorMessage);
      setListStatus("error");
    } finally {
      setUpdatingId(null);
    }
  }, [filters]);

  const loadSummary = useCallback(async () => {
    setSummaryStatus("loading");
    setSummaryError("");
    try {
      setSummary(await getIncidentSummary());
      setSummaryStatus("success");
    } catch {
      setSummaryError(summaryErrorMessage);
      setSummaryStatus("error");
    } finally {
      setUpdatingId(null);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadIncidents();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadIncidents]);
  useEffect(() => {
    const timer = window.setTimeout(() => { void loadSummary(); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadSummary]);

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
      setErrorMessage(statusErrorMessage);
      setListStatus("error");
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

    <IncidentSummary summary={summary} status={summaryStatus} error={summaryError} onRetry={() => { void loadSummary(); }} />

    <section className="rounded-3xl border border-white/10 bg-[var(--panel)] p-5 shadow-xl shadow-black/25 md:p-6">
      <div className="flex items-center justify-between gap-3"><h2 className="text-xl font-semibold text-white">Listado</h2><button type="button" onClick={() => { void loadIncidents(); }} className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm text-slate-200">Reintentar</button></div>
      {listStatus === "loading" ? <LoadingBlock label="Cargando incidencias..." /> : null}
      {listStatus === "error" ? <ErrorBlock message={errorMessage || listErrorMessage} onRetry={() => { void loadIncidents(); }} /> : null}
      {listStatus === "success" && incidents.length === 0 ? <p className="mt-5 rounded-xl border border-dashed border-slate-600 p-5 text-sm text-slate-300">No hay incidencias para los filtros seleccionados.</p> : null}
      {listStatus === "success" && incidents.length > 0 ? <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead className="text-xs tracking-wide text-slate-400 uppercase"><tr><th className="pb-3">Incidencia</th><th className="pb-3">Categoría</th><th className="pb-3">Sede</th><th className="pb-3">Estado</th></tr></thead><tbody className="divide-y divide-white/10">{incidents.map((incident) => <tr key={incident.id}><td className="py-3 pr-4"><p className="font-semibold text-white">{incident?.title || "Incidencia sin título"}</p><p className="text-xs text-slate-400">{incident?.origin || "origen desconocido"} · {incident?.id || "sin id"}</p></td><td className="py-3 pr-4 text-slate-300">{incident?.category || "Sin categoría"}</td><td className="py-3 pr-4 text-slate-300">{incident?.branch || "Sin sede"}</td><td className="py-3"><select disabled={updatingId === incident?.id || incident?.status === "resolved" || incident?.status === "discarded"} value={incident?.status || "open"} onChange={(event) => void changeStatus(incident, event.target.value as IncidentStatus)} className="rounded-lg border border-slate-600 bg-[var(--panel-soft)] px-2 py-1 text-slate-100"><option value={incident?.status || "open"}>{incident?.status || "open"}</option>{allowedNextStatuses(incident?.status || "open").map((status) => <option key={status} value={status}>{status}</option>)}</select></td></tr>)}</tbody></table></div> : null}
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

function IncidentSummary({ summary, status, error, onRetry }: { summary: IncidentSummaryData | null; status: AsyncStatus; error: string; onRetry: () => void }) {
  if (status === "error") return <section className="rounded-3xl border border-rose-300/20 bg-rose-300/10 p-5"><ErrorBlock message={error || summaryErrorMessage} onRetry={onRetry} /></section>;
  if (status === "loading" || !summary) return <section className="rounded-3xl border border-white/10 bg-[var(--panel)] p-5"><LoadingBlock label="Cargando resumen..." /></section>;
  return <section className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <MetricCard label="Total" value={summary?.total ?? 0} />
      {Object.entries(summary?.by_status ?? {}).map(([label, value]) => <MetricCard key={`status-${label}`} label={label} value={value} />)}
    </div>
    <div className="grid gap-4 lg:grid-cols-3">
      <MetricGroup title="Por categoría" values={summary?.by_category ?? {}} />
      <MetricGroup title="Por origen" values={summary?.by_origin ?? {}} />
      <MetricGroup title="Por sede" values={summary?.by_branch ?? {}} />
    </div>
  </section>;
}

function MetricCard({ label, value }: { label: string; value: number }) {
  return <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4"><p className="text-xs tracking-wide text-slate-400 uppercase">{label}</p><p className="mt-1 text-2xl font-semibold text-white">{value}</p></article>;
}

function MetricGroup({ title, values }: { title: string; values: Record<string, number> }) {
  return <article className="rounded-2xl border border-white/10 bg-[var(--panel)] p-4"><h3 className="text-sm font-semibold text-cyan-200">{title}</h3><dl className="mt-3 space-y-2">{Object.entries(values).map(([label, value]) => <div key={label} className="flex items-center justify-between gap-3 text-sm"><dt className="text-slate-300">{label}</dt><dd className="font-semibold text-white">{value}</dd></div>)}</dl></article>;
}

function LoadingBlock({ label }: { label: string }) {
  return <div className="mt-5 flex items-center gap-3 text-sm text-cyan-200"><span className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-200 border-t-transparent" />{label}</div>;
}

function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div role="alert" className="mt-5 flex flex-col gap-3 rounded-xl border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-200 sm:flex-row sm:items-center sm:justify-between"><span>{message}</span><button type="button" onClick={onRetry} className="rounded-lg border border-rose-200/50 px-3 py-1.5 font-semibold text-rose-100 hover:bg-rose-200/10">Reintentar</button></div>;
}
