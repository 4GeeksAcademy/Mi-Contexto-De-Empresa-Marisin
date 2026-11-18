import type { AnalysisResult } from "@/lib/incidents";

type AnalysisResultsProps = {
  result: AnalysisResult;
  onDownload: () => void;
  downloadLoading: boolean;
  downloadError: string | null;
  onRetryDownload: () => void | Promise<void>;
};

export function AnalysisResults({
  result,
  onDownload,
  downloadLoading,
  downloadError,
  onRetryDownload,
}: AnalysisResultsProps) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-2xl font-bold text-slate-800">
          Resultados del Analisis
        </h2>
        <button
          onClick={onDownload}
          disabled={downloadLoading}
          className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:bg-slate-400"
        >
          {downloadLoading ? "Preparando CSV..." : "Descargar Resultados en CSV"}
        </button>
      </div>
      {downloadError ? (
        <ErrorBlock
          message={downloadError}
          onRetry={onRetryDownload}
          disabled={downloadLoading}
        />
      ) : null}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <MetricCard
          label="Total Elementos"
          value={result.total_elements}
          tone="text-slate-800"
        />
        <MetricCard
          label="Registros Validos"
          value={result.valid_records}
          tone="text-emerald-600"
        />
        <MetricCard
          label="Registros Invalidos"
          value={result.invalid_records}
          tone="text-red-600"
        />
        <MetricCard
          label="Satisfaccion Promedio"
          value={`${result.avg_satisfaction ?? 0} / 5`}
          tone="text-blue-600"
        />
      </div>

      {result.invalid_records > 0 ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
          <p className="mb-1 font-semibold">
            Se han detectado registros invalidos en el fichero:
          </p>
          <ul className="list-inside list-disc space-y-1">
            <li>
              Campos vacios o faltantes:{" "}
              <strong>{result.invalid_reasons?.missing_fields ?? 0}</strong>
            </li>
            <li>
              Categorias no reconocidas:{" "}
              <strong>{result.invalid_reasons?.invalid_category ?? 0}</strong>
            </li>
            <li>
              Estados no reconocidos:{" "}
              <strong>{result.invalid_reasons?.invalid_status ?? 0}</strong>
            </li>
          </ul>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <BreakdownCard
          title="Desglose por Categoria"
          values={result.category_breakdown ?? {}}
        />
        <BreakdownCard
          title="Desglose por Estado"
          values={result.status_breakdown ?? {}}
        />
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <p className="text-sm font-medium text-slate-500">{label}</p>
      <p className={`mt-1 text-3xl font-bold ${tone}`}>{value}</p>
    </div>
  );
}

function BreakdownCard({
  title,
  values,
}: {
  title: string;
  values: Record<string, number>;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <h3 className="mb-4 text-lg font-bold text-slate-800">{title}</h3>
      <div className="space-y-3">
        {Object.entries(values).map(([label, count]) => (
          <div
            key={label}
            className="flex items-center justify-between border-b border-slate-100 pb-2"
          >
            <span className="font-medium text-slate-600">{label}</span>
            <span className="rounded-md bg-slate-100 px-2.5 py-1 text-sm font-semibold text-slate-800">
              {count}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ErrorBlock({
  message,
  onRetry,
  disabled,
}: {
  message: string;
  onRetry: () => void | Promise<void>;
  disabled?: boolean;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 sm:flex-row sm:items-center sm:justify-between"
    >
      <span>{message}</span>
      <button
        type="button"
        onClick={() => {
          void onRetry();
        }}
        disabled={disabled}
        className="rounded-md border border-red-300 px-3 py-1.5 font-semibold text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
      >
        Reintentar
      </button>
    </div>
  );
}
