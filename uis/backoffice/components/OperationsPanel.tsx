"use client";

import { useEffect, useState } from "react";

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
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const params = new URLSearchParams();
    if (selectedOrigin !== "all") params.set("origin", selectedOrigin);
    if (trackingLookup.trim().length > 0) params.set("tracking", trackingLookup.trim());

    let ignore = false;
    const loadSnapshot = async () => {
      setIsLoading(true);
      setErrorMessage("");

      try {
        const response = await fetch(`/api/operations?${params.toString()}`, { cache: "no-store" });
        if (!response.ok) {
          throw new Error("No fue posible cargar el resumen operativo");
        }

        const payload = (await response.json()) as OperationSnapshot;
        if (!ignore) {
          setSnapshot(payload);
        }
      } catch (error) {
        if (!ignore) {
          setErrorMessage(error instanceof Error ? error.message : "No fue posible cargar el resumen operativo");
        }
      } finally {
        if (!ignore) {
          setIsLoading(false);
        }
      }
    };

    void loadSnapshot();
    return () => {
      ignore = true;
    };
  }, [selectedOrigin, trackingLookup]);

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

      {isLoading ? <p className="mb-3 text-sm text-cyan-200">Actualizando resumen operativo...</p> : null}
      {errorMessage ? <p className="mb-3 text-sm text-rose-300">{errorMessage}</p> : null}

      {snapshot ? (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard title="SKUs activos" value={snapshot.stockReport.totalSKUs.toString()} detail={`Stock global: ${snapshot.stockReport.globalTotalStock}`} />
            <KpiCard title="Envios analizados" value={snapshot.carrierReport.totalShipments.toString()} detail={`Incidencias: ${snapshot.carrierReport.totalIncidents}`} />
            <KpiCard
              title="Coste promedio"
              value={`${snapshot.carrierReport.averageCostEuro.toFixed(2)} EUR`}
              detail={`Total: ${snapshot.carrierReport.totalCostEuro.toFixed(2)} EUR`}
            />
            <KpiCard
              title="Resolucion tickets"
              value={`${snapshot.customerReport.resolutionRatePercentage.toFixed(1)}%`}
              detail={`Abiertos: ${snapshot.customerReport.totalTickets - snapshot.customerReport.resolvedTickets}`}
            />
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-2">
            <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4">
              <h3 className="text-sm font-semibold tracking-wide text-cyan-200 uppercase">Alertas y riesgos</h3>
              <ul className="mt-3 space-y-2 text-sm text-slate-200">
                <li>SKUs con stock bajo: {snapshot.lowStockSkus.length}</li>
                <li>Clientes con alto riesgo de churn: {snapshot.atRiskClients.length}</li>
                <li>Devoluciones con revision humana obligatoria: {snapshot.mandatoryHumanReview}</li>
                <li>Valor medio devoluciones: {snapshot.returnsReport.averageValueEuro.toFixed(2)} EUR</li>
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
                    {snapshot.trackingResult.trackingNumber} · {snapshot.trackingResult.carrierName} · {snapshot.trackingResult.status} · {snapshot.trackingResult.costEuro} EUR
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
                {snapshot.expensiveShipments.map((shipment) => (
                  <li key={shipment.id} className="flex items-center justify-between gap-2">
                    <span>
                      {shipment.id} · {shipment.carrierName}
                    </span>
                    <span className="font-semibold text-amber-300">{shipment.costEuro.toFixed(2)} EUR</span>
                  </li>
                ))}
              </ul>
            </article>

            <article className="rounded-2xl border border-white/10 bg-[var(--panel-soft)] p-4">
              <h3 className="text-sm font-semibold tracking-wide text-cyan-200 uppercase">Agrupacion por carrier</h3>
              <ul className="mt-3 space-y-2 text-sm text-slate-200">
                {Object.entries(snapshot.shipmentByCarrier).map(([carrier, carrierShipments]) => (
                  <li key={carrier} className="flex items-center justify-between gap-2">
                    <span>{carrier}</span>
                    <span className="rounded-full bg-[#213759] px-2 py-0.5 text-xs text-cyan-100">{carrierShipments.length} envios</span>
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

function KpiCard({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <article className="rounded-2xl border border-white/10 bg-[#1b2e4a] p-4">
      <p className="text-xs tracking-wide text-slate-300 uppercase">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-white">{value}</p>
      <p className="mt-1 text-xs text-slate-400">{detail}</p>
    </article>
  );
}
