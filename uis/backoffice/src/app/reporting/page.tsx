"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError } from "@/lib/api";
import { getProducts } from "@/lib/inventory";
import {
  KPI_DEFINITIONS,
  addWeeks,
  currentWeekStart,
  formatDateTime,
  formatKpi,
  formatWeekRange,
  getLatestPipelineRun,
  getWeeklyPerformance,
  warehouseLabel,
  weeklyTotals,
  type KpiDefinition,
  type PipelineRunSummary,
  type WeeklyPerformanceEntry,
  type WeeklyPerformanceReport,
} from "@/lib/reporting";
import { toClientId } from "@/lib/telemetry-mappers";

// Reporte Semanal de Desempeño por Almacén y Cliente (BRIEFING de data pipelines).
// Pensado para Thomas (CEO) y Ana (Operaciones de Almacén): solo números de negocio.
export default function WeeklyPerformancePage() {
  const [requestedWeek, setRequestedWeek] = useState<string | null>(null);
  const [report, setReport] = useState<WeeklyPerformanceReport | null>(null);
  const [emptyWeek, setEmptyWeek] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [latestRun, setLatestRun] = useState<PipelineRunSummary | null>(null);
  const [clientNames, setClientNames] = useState<Map<string, string>>(new Map());

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    setEmptyWeek(null);
    getWeeklyPerformance(requestedWeek)
      .then((data) => {
        if (active) setReport(data);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setReport(null);
        if (reason instanceof ApiError && reason.status === 404) {
          setEmptyWeek(requestedWeek);
        } else {
          setError(reason instanceof Error ? reason.message : "No se pudo cargar el reporte.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [requestedWeek]);

  useEffect(() => {
    getLatestPipelineRun().then(setLatestRun).catch(() => setLatestRun(null));
    // Nombres comerciales de los clientes (EcoWear USA en lugar de ecowear_usa).
    getProducts()
      .then((products) => {
        const names = new Map<string, string>();
        for (const product of products) {
          const id = toClientId(product.client_name);
          if (id) names.set(id, product.client_name);
        }
        setClientNames(names);
      })
      .catch(() => setClientNames(new Map()));
  }, []);

  const shownWeek = report?.week_start ?? emptyWeek;
  const thisWeek = currentWeekStart();
  const entries = useMemo(() => report?.entries ?? [], [report]);
  const totals = useMemo(() => weeklyTotals(entries), [entries]);

  function clientLabel(clientId: string): string {
    return clientNames.get(clientId) ?? clientId;
  }

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold text-gray-900">
          Reporte semanal de desempeño por almacén y cliente
        </h1>
        <p className="text-sm text-gray-500">
          Volumen de entrada, throughput de salida, quiebres de stock y precisión de inventario de
          cada cliente en Los Ángeles y Zaragoza.
        </p>
      </div>

      <section
        aria-label="Periodo del reporte"
        className="flex flex-wrap items-center justify-between gap-3 bg-white p-4 shadow rounded-lg border border-gray-200"
      >
        <div>
          <p className="text-xs uppercase tracking-wide text-gray-500">Periodo</p>
          <p className="text-lg font-semibold text-gray-900">
            {shownWeek ? formatWeekRange(shownWeek) : "Última semana calculada"}
          </p>
          {shownWeek === thisWeek && (
            <p className="text-sm text-amber-700">Semana en curso: los datos aún son parciales.</p>
          )}
          {latestRun?.finished_at && (
            <p className="text-sm text-gray-500">
              Última actualización: {formatDateTime(latestRun.finished_at)}
              {latestRun.status === "failed" && " (falló; se muestran los datos anteriores)"}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!shownWeek || loading}
            onClick={() => shownWeek && setRequestedWeek(addWeeks(shownWeek, -1))}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
          >
            ← Semana anterior
          </button>
          <button
            type="button"
            disabled={!shownWeek || loading || addWeeks(shownWeek, 1) > thisWeek}
            onClick={() => shownWeek && setRequestedWeek(addWeeks(shownWeek, 1))}
            className="rounded-md border border-gray-300 px-3 py-2 text-sm text-gray-700 hover:bg-gray-100 disabled:opacity-50"
          >
            Semana siguiente →
          </button>
          <button
            type="button"
            disabled={requestedWeek === null || loading}
            onClick={() => setRequestedWeek(null)}
            className="rounded-md bg-gray-800 px-3 py-2 text-sm text-white hover:bg-gray-900 disabled:opacity-50"
          >
            Última semana calculada
          </button>
        </div>
      </section>

      {error && (
        <div role="alert" className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-md">
          {error}
        </div>
      )}

      {loading && <p role="status" className="text-gray-500">Cargando el reporte...</p>}

      {!loading && !error && entries.length === 0 && (
        <div role="status" className="p-4 bg-gray-50 border border-gray-200 text-gray-700 rounded-md">
          {shownWeek
            ? `No hay datos calculados para la ${formatWeekRange(shownWeek).toLowerCase()}.`
            : "Todavía no hay ninguna semana calculada."}
        </div>
      )}

      {!loading && entries.length > 0 && (
        <>
          <section aria-label="Resumen de la semana" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {KPI_DEFINITIONS.map((kpi) => (
              <div key={kpi.key} className="bg-white p-4 shadow rounded-lg border border-gray-200">
                <p className="text-sm font-medium text-gray-600">{kpi.name}</p>
                <p className="mt-1 text-3xl font-bold text-gray-900">
                  {formatKpi(kpi.key, totals[kpi.key])}
                </p>
                <p className="text-xs text-gray-500">
                  {kpi.key === "discrepancy_rate"
                    ? `${totals.discrepancy_events_count} discrepancias / ${totals.outbound_orders_count} pedidos`
                    : `${kpi.unit} en total`}
                </p>
              </div>
            ))}
          </section>

          {KPI_DEFINITIONS.map((kpi) => (
            <KpiBreakdown
              key={kpi.key}
              kpi={kpi}
              entries={entries}
              clientLabel={clientLabel}
            />
          ))}
        </>
      )}
    </div>
  );
}

function KpiBreakdown({
  kpi,
  entries,
  clientLabel,
}: {
  kpi: KpiDefinition;
  entries: WeeklyPerformanceEntry[];
  clientLabel: (clientId: string) => string;
}) {
  const rows = [...entries].sort((a, b) => b[kpi.key] - a[kpi.key]);
  const max = Math.max(...rows.map((row) => row[kpi.key]), 0);

  return (
    <section
      aria-labelledby={`kpi-${kpi.key}`}
      className="bg-white p-6 shadow rounded-lg border border-gray-200 space-y-3"
    >
      <div>
        <h2 id={`kpi-${kpi.key}`} className="text-lg font-semibold text-gray-900">
          {kpi.name}
        </h2>
        <p className="text-sm text-gray-500">{kpi.description}</p>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-gray-500 border-b border-gray-200">
            <th className="py-2 pr-4 font-medium">Almacén</th>
            <th className="py-2 pr-4 font-medium">Cliente</th>
            <th className="py-2 pr-4 font-medium text-right">{kpi.name}</th>
            <th className="py-2 font-medium w-1/3" aria-hidden="true"></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const value = row[kpi.key];
            const width = max > 0 ? Math.round((value / max) * 100) : 0;
            return (
              <tr key={`${row.warehouse}-${row.client_id}`} className="border-b border-gray-100 last:border-0">
                <td className="py-2 pr-4 text-gray-700">{warehouseLabel(row.warehouse)}</td>
                <td className="py-2 pr-4 text-gray-900 font-medium">{clientLabel(row.client_id)}</td>
                <td className="py-2 pr-4 text-right tabular-nums text-gray-900">
                  {formatKpi(kpi.key, value)}
                  {kpi.key === "discrepancy_rate" && (
                    <span className="block text-xs text-gray-500">
                      {row.discrepancy_events_count} / {row.outbound_orders_count} pedidos
                    </span>
                  )}
                </td>
                <td className="py-2" aria-hidden="true">
                  <div className="h-3 rounded bg-gray-100">
                    <div className="h-3 rounded bg-gray-700" style={{ width: `${width}%` }} />
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
