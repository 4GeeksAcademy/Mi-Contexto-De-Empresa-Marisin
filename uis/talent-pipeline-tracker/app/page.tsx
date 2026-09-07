"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import CandidateFilters from "@/components/CandidateFilters";
import CandidateFormModal from "@/components/CandidateFormModal";
import { getCandidates } from "@/services/api";
import { Candidate } from "@/types";

type UiState = "loading" | "success" | "error";

export default function Home() {
  const searchParams = useSearchParams();
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [uiState, setUiState] = useState<UiState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const filters = useMemo(
    () => ({
      status: searchParams.get("status") || "",
      stage: searchParams.get("stage") || "",
      search: searchParams.get("search") || "",
    }),
    [searchParams]
  );

  useEffect(() => {
    let isCancelled = false;

    const loadCandidates = async () => {
      setUiState("loading");
      setErrorMessage("");

      try {
        const data = await getCandidates({
          status: filters.status || undefined,
          stage: filters.stage || undefined,
          search: filters.search || undefined,
        });

        if (isCancelled) return;
        setCandidates(Array.isArray(data) ? data : []);
        setUiState("success");
      } catch (error) {
        if (isCancelled) return;
        setUiState("error");
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "No se pudieron cargar las candidaturas de TrackFlow"
        );
      }
    };

    void loadCandidates();

    return () => {
      isCancelled = true;
    };
  }, [filters.search, filters.stage, filters.status, refreshNonce]);

  const refreshCandidates = () => {
    setRefreshNonce((prev) => prev + 1);
  };

  return (
    <div className="min-h-screen bg-[linear-gradient(160deg,#f8fafc_0%,#e2e8f0_42%,#f1f5f9_100%)] px-4 py-8 text-slate-900 sm:px-6 lg:px-10">
      <main className="mx-auto w-full max-w-6xl">
        <header className="rounded-2xl border border-slate-200/80 bg-white/95 p-6 shadow-lg shadow-slate-200/70 backdrop-blur sm:p-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
                TrackFlow · People & Talent
              </p>
              <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
                Talent Pipeline Tracker
              </h1>
              <p className="mt-2 max-w-2xl text-sm text-slate-600 sm:text-base">
                Dashboard principal para seguimiento de candidaturas, estado del
                proceso y etapa de selección del equipo interno de People &
                Talent.
              </p>
            </div>

            <button
              type="button"
              onClick={() => setIsModalOpen(true)}
              className="inline-flex items-center justify-center rounded-xl bg-cyan-700 px-5 py-3 text-sm font-semibold text-white transition hover:bg-cyan-800"
            >
              Registrar Candidatura
            </button>
          </div>
        </header>

        <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-6">
          <CandidateFilters />
        </section>

        <section className="mt-6">
          {uiState === "loading" && (
            <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
              <div className="mb-5 flex items-center gap-3 text-slate-700">
                <span className="h-5 w-5 animate-spin rounded-full border-2 border-cyan-700 border-t-transparent" />
                <p className="font-medium">Cargando candidaturas...</p>
              </div>
              <div className="grid gap-4">
                {[1, 2, 3].map((item) => (
                  <div
                    key={item}
                    className="animate-pulse rounded-xl border border-slate-200 p-4"
                  >
                    <div className="h-4 w-1/3 rounded bg-slate-200" />
                    <div className="mt-3 h-3 w-2/3 rounded bg-slate-100" />
                    <div className="mt-3 h-3 w-1/2 rounded bg-slate-100" />
                  </div>
                ))}
              </div>
            </div>
          )}

          {uiState === "error" && (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-red-900 shadow-sm">
              <h2 className="text-lg font-semibold">Error al cargar el tablero</h2>
              <p className="mt-2 text-sm">{errorMessage}</p>
              <button
                type="button"
                onClick={refreshCandidates}
                className="mt-4 rounded-lg bg-red-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-red-800"
              >
                Reintentar
              </button>
            </div>
          )}

          {uiState === "success" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h2 className="text-xl font-semibold text-slate-900">
                  Candidatos ({candidates.length})
                </h2>
              </div>

              {candidates.length === 0 ? (
                <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-slate-600 shadow-sm">
                  No hay candidaturas que coincidan con tus filtros.
                </div>
              ) : (
                <ul className="grid gap-4">
                  {candidates.map((candidate) => (
                    <li key={candidate.id}>
                      <Link
                        href={`/candidates/${candidate.id}`}
                        className="block rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-cyan-300 hover:shadow-md"
                      >
                        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                          <div>
                            <h3 className="text-lg font-semibold text-slate-900">
                              {candidate.name}
                            </h3>
                            <p className="mt-1 text-sm text-slate-600">
                              {candidate.email}
                            </p>
                            <p className="mt-2 text-sm font-medium text-slate-700">
                              Puesto: {candidate.position}
                            </p>
                          </div>

                          <div className="flex flex-wrap gap-2">
                            <span className="rounded-full bg-cyan-50 px-3 py-1 text-xs font-semibold text-cyan-700">
                              Estado: {candidate.status}
                            </span>
                            <span className="rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
                              Etapa: {candidate.stage}
                            </span>
                          </div>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      </main>

      <CandidateFormModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onCreated={() => {
          setIsModalOpen(false);
          refreshCandidates();
        }}
      />
    </div>
  );
}
