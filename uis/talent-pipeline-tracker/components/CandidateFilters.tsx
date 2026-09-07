"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

export default function CandidateFilters() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const status = searchParams.get("status") || "";
  const stage = searchParams.get("stage") || "";
  const search = searchParams.get("search") || "";

  const updateUrlParams = (
    nextStatus: string,
    nextStage: string,
    nextSearch: string
  ) => {
    const params = new URLSearchParams(searchParams.toString());

    if (nextStatus.trim()) {
      params.set("status", nextStatus.trim());
    } else {
      params.delete("status");
    }

    if (nextStage.trim()) {
      params.set("stage", nextStage.trim());
    } else {
      params.delete("stage");
    }

    if (nextSearch.trim()) {
      params.set("search", nextSearch.trim());
    } else {
      params.delete("search");
    }

    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  };

  const handleClearFilters = () => {
    router.replace(pathname);
  };

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">
          Filtros de Candidaturas
        </h2>
        <button
          type="button"
          onClick={handleClearFilters}
          className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
        >
          Limpiar filtros
        </button>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">Estado</span>
          <input
            type="text"
            placeholder="Ej: Activa"
            value={status}
            onChange={(event) => {
              const value = event.target.value;
              updateUrlParams(value, stage, search);
            }}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-cyan-500"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">Etapa</span>
          <input
            type="text"
            placeholder="Ej: Entrevista Técnica"
            value={stage}
            onChange={(event) => {
              const value = event.target.value;
              updateUrlParams(status, value, search);
            }}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-cyan-500"
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">
            Buscar por nombre o email
          </span>
          <input
            type="text"
            placeholder="Ej: Ana o ana@trackflow.com"
            value={search}
            onChange={(event) => {
              const value = event.target.value;
              updateUrlParams(status, stage, value);
            }}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-cyan-500"
          />
        </label>
      </div>
    </div>
  );
}