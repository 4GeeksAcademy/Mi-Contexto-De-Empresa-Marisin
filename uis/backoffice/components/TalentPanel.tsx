"use client";

import { useMemo, useState } from "react";
import { getCandidates } from "../../talent-pipeline-tracker/services/api";
import type { Candidate } from "../../talent-pipeline-tracker/types";

type UiState = "idle" | "loading" | "success" | "error";

export function TalentPanel() {
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [uiState, setUiState] = useState<UiState>("idle");
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [errorMessage, setErrorMessage] = useState("");

  const statusDistribution = useMemo(() => {
    return candidates.reduce<Record<string, number>>((acc, item) => {
      acc[item.status] = (acc[item.status] || 0) + 1;
      return acc;
    }, {});
  }, [candidates]);

  const stageDistribution = useMemo(() => {
    return candidates.reduce<Record<string, number>>((acc, item) => {
      acc[item.stage] = (acc[item.stage] || 0) + 1;
      return acc;
    }, {});
  }, [candidates]);

  const loadCandidates = async () => {
    setUiState("loading");
    setErrorMessage("");

    try {
      const data = await getCandidates({
        status: statusFilter || undefined,
        search: search || undefined,
      });

      setCandidates(Array.isArray(data) ? data : []);
      setUiState("success");
    } catch (error) {
      setUiState("error");
      setErrorMessage(error instanceof Error ? error.message : "No se pudo cargar el Talent Pipeline Tracker");
    }
  };

  return (
    <section className="rounded-3xl border border-white/10 bg-[var(--panel)] p-5 shadow-xl shadow-black/25 md:p-6">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Talent Pipeline Tracker (Hito 3)</h2>
          <p className="mt-1 text-sm text-slate-300">Consumido desde el servicio existente del monorepo, sin duplicar logica.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Buscar por nombre o email"
            className="rounded-lg border border-slate-600 bg-[var(--panel-soft)] px-3 py-2 text-sm text-slate-100"
          />
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="rounded-lg border border-slate-600 bg-[var(--panel-soft)] px-3 py-2 text-sm text-slate-100"
          >
            <option value="">Todos los estados</option>
            <option value="new">new</option>
            <option value="screening">screening</option>
            <option value="interview">interview</option>
            <option value="offer">offer</option>
            <option value="hired">hired</option>
            <option value="rejected">rejected</option>
          </select>
          <button
            type="button"
            onClick={() => {
              void loadCandidates();
            }}
            className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400"
          >
            Cargar
          </button>
        </div>
      </div>

      {uiState === "idle" ? <p className="text-sm text-slate-300">Pulsa Cargar para consultar candidaturas actuales.</p> : null}
      {uiState === "loading" ? <p className="text-sm text-cyan-200">Consultando candidaturas...</p> : null}
      {uiState === "error" ? <p className="text-sm text-rose-300">{errorMessage}</p> : null}

      {uiState === "success" ? (
        <>
          <div className="grid gap-3 md:grid-cols-3">
            <Metric title="Total candidatos" value={String(candidates.length)} />
            <Metric title="Estados distintos" value={String(Object.keys(statusDistribution).length)} />
            <Metric title="Etapas distintas" value={String(Object.keys(stageDistribution).length)} />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4">
              <h3 className="text-sm font-semibold tracking-wide text-cyan-200 uppercase">Listado de candidaturas</h3>
              {candidates.length === 0 ? (
                <p className="mt-3 text-sm text-slate-300">No hay resultados para el filtro seleccionado.</p>
              ) : (
                <ul className="mt-3 max-h-80 space-y-2 overflow-auto pr-1">
                  {candidates.slice(0, 15).map((candidate) => (
                    <li key={candidate.id} className="rounded-xl border border-white/10 bg-[#12233e] p-3 text-sm text-slate-100">
                      <p className="font-semibold">{candidate.name}</p>
                      <p className="text-xs text-slate-300">{candidate.email}</p>
                      <p className="mt-1 text-xs text-cyan-100">{candidate.position}</p>
                      <p className="mt-1 text-xs text-slate-300">
                        Estado: {candidate.status} · Etapa: {candidate.stage}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </article>

            <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4">
              <h3 className="text-sm font-semibold tracking-wide text-cyan-200 uppercase">Distribucion por estado</h3>
              <ul className="mt-3 space-y-2 text-sm text-slate-200">
                {Object.entries(statusDistribution).map(([label, count]) => (
                  <li key={label} className="flex items-center justify-between">
                    <span>{label}</span>
                    <span className="rounded-full bg-[#213759] px-2 py-0.5 text-xs">{count}</span>
                  </li>
                ))}
              </ul>
              <h3 className="mt-4 text-sm font-semibold tracking-wide text-cyan-200 uppercase">Distribucion por etapa</h3>
              <ul className="mt-3 space-y-2 text-sm text-slate-200">
                {Object.entries(stageDistribution).map(([label, count]) => (
                  <li key={label} className="flex items-center justify-between">
                    <span>{label}</span>
                    <span className="rounded-full bg-[#213759] px-2 py-0.5 text-xs">{count}</span>
                  </li>
                ))}
              </ul>
            </article>
          </div>
        </>
      ) : null}
    </section>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <article className="rounded-2xl border border-white/10 bg-[#1b2e4a] p-4">
      <p className="text-xs tracking-wide text-slate-300 uppercase">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
    </article>
  );
}
