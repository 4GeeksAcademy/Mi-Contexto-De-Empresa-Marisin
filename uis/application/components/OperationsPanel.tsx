"use client";

import { useCallback, useEffect, useState } from "react";

type AsyncStatus = "loading" | "success" | "error";

const operationsErrorMessage = "No fue posible cargar el resumen operativo. Revisa la conexión y vuelve a intentarlo.";

type OperationSnapshot = {
  stockReport: {
    totalSKUs: number;
    globalTotalStock: number;
  };
  carrierReport: {
    totalShipments: number;
    totalCostEuro: number;
    averageCostEuro: number;
    totalIncidents: number;
  };
  returnsReport: {
    averageValueEuro: number;
  };
  customerReport: {
    totalTickets: number;
    resolvedTickets: number;
    resolutionRatePercentage: number;
  };
  lowStockSkus: Array<{ sku: string }>;
  shipmentByCarrier: Record<string, unknown[]>;
  expensiveShipments: Array<{ id: string; carrierName: string; costEuro: number }>;
  trackingResult: { trackingNumber: string; carrierName: string; status: string; costEuro: number } | null;
  atRiskClients: Array<{ id: string }>;
  mandatoryHumanReview: number;
};

export function OperationsPanel() {
  const [selectedOrigin, setSelectedOrigin] = useState<"all" | "Los Angeles" | "Zaragoza">("all");
  const [trackingLookup, setTrackingLookup] = useState("TRK-SEUR-02");
  const [snapshot, setSnapshot] = useState<OperationSnapshot | null>(null);
  const [status, setStatus] = useState<AsyncStatus>("loading");
  const [errorMessage, setErrorMessage] = useState("");

  const loadSnapshot = useCallback(async (shouldIgnore: () => boolean = () => false) => {
    const params = new URLSearchParams();
    if (selectedOrigin !== "all") params.set("origin", selectedOrigin);
    if (trackingLookup.trim().length > 0) params.set("tracking", trackingLookup.trim());

    setStatus("loading");
    setErrorMessage("");

    try {
      const response = await fetch(`/api/operations?${params.toString()}`, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(operationsErrorMessage);
      }

      let payload: OperationSnapshot;
      try {
        payload = (await response.json()) as OperationSnapshot;
      } catch {
        throw new Error("La respuesta operativa no se pudo interpretar. Inténtalo de nuevo.");
      }

      if (!shouldIgnore()) {
        setSnapshot(payload);
        setStatus("success");
      }
    } catch {
      if (!shouldIgnore()) {
        setErrorMessage(operationsErrorMessage);
        setStatus("error");
      }
    } finally {
      if (shouldIgnore()) return;
    }
  }, [selectedOrigin, trackingLookup]);

  useEffect(() => {
    let ignore = false;
    const timer = window.setTimeout(() => {
      void loadSnapshot(() => ignore);
    }, 0);
    return () => {
      ignore = true;
      window.clearTimeout(timer);
    };
  }, [loadSnapshot]);

  return (
    <section className="rounded-3xl border border-white/10 bg-[var(--panel)] p-5 shadow-xl shadow-black/25 md:p-6">
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <h2 className="text-xl font-semibold text-white">Resumen operativo (Hito 2)</h2>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          Filtrar por origen:
          <select
            className="rounded-lg border border-slate-600 bg-[var(--panel-soft)] px-2 py-1 text-slate-100"
            value={selectedOrigin}
            onChange={(event) => setSelectedOrigin(event.target.value as "all" | "Los Angeles" | "Zaragoza")}
          >
            <option value="all">Todos</option>
            <option value="Los Angeles">Los Angeles</option>
            <option value="Zaragoza">Zaragoza</option>
          </select>
        </label>
      </div>

      {status === "loading" ? <LoadingBlock label="Actualizando resumen operativo..." /> : null}
      {status === "error" ? <ErrorBlock message={errorMessage || operationsErrorMessage} onRetry={() => { void loadSnapshot(); }} /> : null}

      {status === "success" && snapshot ? (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard title="SKUs activos" value={(snapshot?.stockReport?.totalSKUs ?? 0).toString()} detail={`Stock global: ${snapshot?.stockReport?.globalTotalStock ?? 0}`} />
            <KpiCard title="Envios analizados" value={(snapshot?.carrierReport?.totalShipments ?? 0).toString()} detail={`Incidencias: ${snapshot?.carrierReport?.totalIncidents ?? 0}`} />
            <KpiCard
              title="Coste promedio"
              value={`${(snapshot?.carrierReport?.averageCostEuro ?? 0).toFixed(2)} EUR`}
              detail={`Total: ${(snapshot?.carrierReport?.totalCostEuro ?? 0).toFixed(2)} EUR`}
            />
            <KpiCard
              title="Resolucion tickets"
              value={`${(snapshot?.customerReport?.resolutionRatePercentage ?? 0).toFixed(1)}%`}
              detail={`Abiertos: ${(snapshot?.customerReport?.totalTickets ?? 0) - (snapshot?.customerReport?.resolvedTickets ?? 0)}`}
            />
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4">
              <h3 className="text-sm font-semibold tracking-wide text-cyan-200 uppercase">Alertas y riesgos</h3>
              <ul className="mt-3 space-y-2 text-sm text-slate-200">
                <li>SKUs con stock bajo: {snapshot?.lowStockSkus?.length ?? 0}</li>
                <li>Clientes con alto riesgo de churn: {snapshot?.atRiskClients?.length ?? 0}</li>
                <li>Devoluciones con revision humana obligatoria: {snapshot?.mandatoryHumanReview ?? 0}</li>
                <li>Valor medio devoluciones: {(snapshot?.returnsReport?.averageValueEuro ?? 0).toFixed(2)} EUR</li>
              </ul>
            </article>

            <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4">
              <h3 className="text-sm font-semibold tracking-wide text-cyan-200 uppercase">Lookup de tracking</h3>
              <div className="mt-3 flex flex-col gap-2">
                <input
                  value={trackingLookup}
                  onChange={(event) => setTrackingLookup(event.target.value)}
                  className="rounded-lg border border-slate-600 bg-[#12233e] px-3 py-2 text-sm text-slate-100"
                  placeholder="TRK-UPS-01"
                />
                {snapshot.trackingResult ? (
                  <p className="text-sm text-slate-200">
                    {snapshot?.trackingResult?.trackingNumber || "Sin tracking"} · {snapshot?.trackingResult?.carrierName || "Sin carrier"} · {snapshot?.trackingResult?.status || "Sin estado"} · {snapshot?.trackingResult?.costEuro ?? 0} EUR
                  </p>
                ) : (
                  <p className="text-sm text-[var(--danger)]">Tracking no encontrado.</p>
                )}
              </div>
            </article>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4">
              <h3 className="text-sm font-semibold tracking-wide text-cyan-200 uppercase">Top envios por coste</h3>
              <ul className="mt-3 space-y-2 text-sm text-slate-200">
                {(snapshot?.expensiveShipments ?? []).map((shipment) => (
                  <li key={shipment?.id || `${shipment?.carrierName}-${shipment?.costEuro}`} className="flex items-center justify-between gap-2">
                    <span>
                      {shipment?.id || "Sin id"} · {shipment?.carrierName || "Sin carrier"}
                    </span>
                    <span className="font-semibold text-amber-300">{(shipment?.costEuro ?? 0).toFixed(2)} EUR</span>
                  </li>
                ))}
              </ul>
            </article>

            <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4">
              <h3 className="text-sm font-semibold tracking-wide text-cyan-200 uppercase">Agrupacion por carrier</h3>
              <ul className="mt-3 space-y-2 text-sm text-slate-200">
                {Object.entries(snapshot?.shipmentByCarrier ?? {}).map(([carrier, carrierShipments]) => (
                  <li key={carrier} className="flex items-center justify-between gap-2">
                    <span>{carrier}</span>
                    <span className="rounded-full bg-[#213759] px-2 py-0.5 text-xs text-cyan-100">{carrierShipments?.length ?? 0} envios</span>
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

function LoadingBlock({ label }: { label: string }) {
  return <div className="mb-3 flex items-center gap-3 text-sm text-cyan-200"><span className="h-4 w-4 animate-spin rounded-full border-2 border-cyan-200 border-t-transparent" />{label}</div>;
}

function ErrorBlock({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div role="alert" className="mb-3 flex flex-col gap-3 rounded-xl border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-200 sm:flex-row sm:items-center sm:justify-between"><span>{message}</span><button type="button" onClick={onRetry} className="rounded-lg border border-rose-200/50 px-3 py-1.5 font-semibold text-rose-100 hover:bg-rose-200/10">Reintentar</button></div>;
}

function KpiCard({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <article className="rounded-2xl border border-white/10 bg-[#1b2e4a] p-4">
      <p className="text-xs tracking-wide text-slate-300 uppercase">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{detail}</p>
    </article>
  );
}
