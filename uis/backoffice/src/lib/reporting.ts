import { fetchWithAuth } from "./api";

// --- Contrato de GET /reporting/weekly-warehouse-client-performance (BRIEFING §6) ---
export interface WeeklyPerformanceEntry {
  warehouse: string;
  client_id: string;
  inbound_units_count: number;
  outbound_orders_count: number;
  stockout_events_count: number;
  discrepancy_events_count: number;
  discrepancy_rate: number;
}

export interface WeeklyPerformanceReport {
  week_start: string;
  entries: WeeklyPerformanceEntry[];
}

// --- GET /reporting/pipeline-runs/latest (solo los campos que usa el dashboard) ---
export interface PipelineRunSummary {
  run_id: string;
  status: "running" | "completed" | "failed";
  finished_at: string | null;
  started_at: string;
  window_start: string;
  window_end: string;
}

export type KpiKey =
  | "inbound_units_count"
  | "outbound_orders_count"
  | "stockout_events_count"
  | "discrepancy_rate";

export interface KpiDefinition {
  key: KpiKey;
  name: string;
  description: string;
  unit: string;
}

// Nombres y definiciones exactos de la sección "KPIs a medir" del BRIEFING.
export const KPI_DEFINITIONS: KpiDefinition[] = [
  {
    key: "inbound_units_count",
    name: "Volumen de entrada",
    description: "Unidades de mercancía de cada cliente que recibió el almacén durante la semana.",
    unit: "unidades",
  },
  {
    key: "outbound_orders_count",
    name: "Throughput de salida",
    description: "Pedidos que el almacén preparó y despachó para cada cliente durante la semana.",
    unit: "pedidos",
  },
  {
    key: "stockout_events_count",
    name: "Frecuencia de quiebre de stock",
    description: "Veces que un SKU del cliente cayó por debajo del mínimo configurado en el almacén.",
    unit: "veces",
  },
  {
    key: "discrepancy_rate",
    name: "Tasa de discrepancia",
    description: "Proporción de los pedidos de salida asociados a una discrepancia de inventario detectada.",
    unit: "%",
  },
];

export const WAREHOUSE_LABELS: Record<string, string> = {
  los_angeles: "Los Ángeles (EE. UU.)",
  zaragoza: "Zaragoza (España)",
};

export function warehouseLabel(warehouse: string): string {
  return WAREHOUSE_LABELS[warehouse] ?? warehouse;
}

export function getWeeklyPerformance(weekStart?: string | null): Promise<WeeklyPerformanceReport> {
  const query = weekStart ? `?week_start=${encodeURIComponent(weekStart)}` : "";
  return fetchWithAuth(`/reporting/weekly-warehouse-client-performance${query}`);
}

export function getLatestPipelineRun(): Promise<PipelineRunSummary> {
  return fetchWithAuth("/reporting/pipeline-runs/latest");
}

// --- Semanas ISO (lunes, UTC) ---
function parseIsoDate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day));
}

function toIsoDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function addWeeks(weekStart: string, weeks: number): string {
  const date = parseIsoDate(weekStart);
  date.setUTCDate(date.getUTCDate() + weeks * 7);
  return toIsoDate(date);
}

export function currentWeekStart(now: Date = new Date()): string {
  const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const daysSinceMonday = (today.getUTCDay() + 6) % 7;
  today.setUTCDate(today.getUTCDate() - daysSinceMonday);
  return toIsoDate(today);
}

export function formatWeekRange(weekStart: string): string {
  const start = parseIsoDate(weekStart);
  const end = parseIsoDate(addWeeks(weekStart, 1));
  end.setUTCDate(end.getUTCDate() - 1);
  const full = new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  if (start.getUTCMonth() === end.getUTCMonth() && start.getUTCFullYear() === end.getUTCFullYear()) {
    return `Semana del ${start.getUTCDate()} al ${full.format(end)}`;
  }
  return `Semana del ${full.format(start)} al ${full.format(end)}`;
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("es-ES", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

const integerFormat = new Intl.NumberFormat("es-ES");
const percentFormat = new Intl.NumberFormat("es-ES", { style: "percent", maximumFractionDigits: 1 });

export function formatKpi(key: KpiKey, value: number): string {
  return key === "discrepancy_rate" ? percentFormat.format(value) : integerFormat.format(value);
}

export interface WeeklyTotals {
  inbound_units_count: number;
  outbound_orders_count: number;
  stockout_events_count: number;
  discrepancy_events_count: number;
  discrepancy_rate: number;
}

// Totales de la semana; la tasa global sigue la misma fórmula del BRIEFING.
export function weeklyTotals(entries: WeeklyPerformanceEntry[]): WeeklyTotals {
  const totals = entries.reduce(
    (sum, entry) => ({
      inbound_units_count: sum.inbound_units_count + entry.inbound_units_count,
      outbound_orders_count: sum.outbound_orders_count + entry.outbound_orders_count,
      stockout_events_count: sum.stockout_events_count + entry.stockout_events_count,
      discrepancy_events_count: sum.discrepancy_events_count + entry.discrepancy_events_count,
    }),
    { inbound_units_count: 0, outbound_orders_count: 0, stockout_events_count: 0, discrepancy_events_count: 0 },
  );
  const discrepancy_rate = totals.outbound_orders_count > 0
    ? totals.discrepancy_events_count / totals.outbound_orders_count
    : 0;
  return { ...totals, discrepancy_rate };
}
