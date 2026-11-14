'use client';

import React, { useState } from 'react';

type UiState = 'idle' | 'loading' | 'success' | 'error';

interface AnalysisResult {
  total_elements: number;
  valid_records: number;
  invalid_records: number;
  invalid_reasons: {
    missing_fields: number;
    invalid_category: number;
    invalid_status: number;
  };
  category_breakdown: Record<string, number>;
  status_breakdown: Record<string, number>;
  avg_satisfaction: number;
}

const analyzeErrorMessage = 'No se pudo analizar el fichero. Revisa que sea un CSV valido y vuelve a intentarlo.';
const downloadErrorMessage = 'No se pudo descargar el CSV de resultados. Vuelve a intentarlo.';

function isAnalysisResult(value: unknown): value is AnalysisResult {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<AnalysisResult>;
  return typeof item.total_elements === 'number' && typeof item.valid_records === 'number' && typeof item.invalid_records === 'number';
}

export default function IncidentsAnalyzePage() {
  const [file, setFile] = useState<File | null>(null);
  const [uiState, setUiState] = useState<UiState>('idle');
  const [downloadLoading, setDownloadLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0] ?? null;
    setFile(selectedFile);
    setError(null);
    setDownloadError(null);
  };

  const runAnalysis = async () => {
    if (!file) {
      setUiState('error');
      setError('Selecciona un fichero CSV antes de ejecutar el analisis.');
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    setUiState('loading');
    setError(null);
    setDownloadError(null);

    try {
      const response = await fetch('/api/incidents/analyze', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error(analyzeErrorMessage);
      }

      let payload: unknown;
      try {
        payload = await response.json();
      } catch {
        throw new Error('La respuesta del analisis no se pudo interpretar. Intentalo de nuevo.');
      }

      if (!isAnalysisResult(payload)) {
        throw new Error('El analisis no devolvio metricas validas. Intentalo de nuevo.');
      }

      setResult(payload);
      setUiState('success');
    } catch {
      setError(analyzeErrorMessage);
      setUiState('error');
    } finally {
      setDownloadLoading(false);
    }
  };

  const handleAnalyze = async (event: React.FormEvent) => {
    event.preventDefault();
    await runAnalysis();
  };

  const handleDownload = async () => {
    setDownloadLoading(true);
    setDownloadError(null);
    try {
      const response = await fetch('/api/incidents/results/export', { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(downloadErrorMessage);
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'results.csv';
      link.click();
      window.URL.revokeObjectURL(url);
    } catch {
      setDownloadError(downloadErrorMessage);
    } finally {
      setDownloadLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl p-8 font-sans">
      <h1 className="mb-2 text-3xl font-bold text-slate-800">Analisis de Incidencias - TrackFlow</h1>
      <p className="mb-6 text-slate-600">Sube el fichero CSV de la empresa para validar registros y ver las metricas operativas.</p>

      <div className="mb-8 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <form onSubmit={handleAnalyze} className="flex flex-col gap-4">
          <div className="cursor-pointer rounded-lg border-2 border-dashed border-slate-300 p-6 text-center transition-colors hover:border-blue-500">
            <input
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              className="block w-full text-sm text-slate-500 file:mr-4 file:rounded-full file:border-0 file:bg-blue-50 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-blue-700 hover:file:bg-blue-100"
            />
            <p className="mt-2 text-sm text-slate-500">Selecciona o arrastra tu fichero CSV corporativo</p>
          </div>

          {uiState === 'loading' ? <LoadingBlock label="Analizando registros..." /> : null}
          {uiState === 'error' && error ? <ErrorBlock message={error} onRetry={runAnalysis} disabled={!file} /> : null}

          <button
            type="submit"
            disabled={uiState === 'loading'}
            className="rounded-lg bg-blue-600 px-4 py-2.5 font-medium text-white transition-colors hover:bg-blue-700 disabled:bg-slate-400"
          >
            {uiState === 'loading' ? 'Analizando registros...' : 'Ejecutar Analisis'}
          </button>
        </form>
      </div>

      {uiState === 'success' && result ? (
        <div className="space-y-6">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-2xl font-bold text-slate-800">Resultados del Analisis</h2>
            <button
              onClick={() => { void handleDownload(); }}
              disabled={downloadLoading}
              className="flex items-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:bg-slate-400"
            >
              {downloadLoading ? 'Preparando CSV...' : 'Descargar Resultados en CSV'}
            </button>
          </div>
          {downloadError ? <ErrorBlock message={downloadError} onRetry={handleDownload} disabled={downloadLoading} /> : null}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
            <MetricCard label="Total Elementos" value={result?.total_elements ?? 0} tone="text-slate-800" />
            <MetricCard label="Registros Validos" value={result?.valid_records ?? 0} tone="text-emerald-600" />
            <MetricCard label="Registros Invalidos" value={result?.invalid_records ?? 0} tone="text-red-600" />
            <MetricCard label="Satisfaccion Promedio" value={`${result?.avg_satisfaction ?? 0} / 5`} tone="text-blue-600" />
          </div>

          {(result?.invalid_records ?? 0) > 0 ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
              <p className="mb-1 font-semibold">Se han detectado registros invalidos en el fichero:</p>
              <ul className="list-inside list-disc space-y-1">
                <li>Campos vacios o faltantes: <strong>{result?.invalid_reasons?.missing_fields ?? 0}</strong></li>
                <li>Categorias no reconocidas: <strong>{result?.invalid_reasons?.invalid_category ?? 0}</strong></li>
                <li>Estados no reconocidos: <strong>{result?.invalid_reasons?.invalid_status ?? 0}</strong></li>
              </ul>
            </div>
          ) : null}

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            <BreakdownCard title="Desglose por Categoria" values={result?.category_breakdown ?? {}} />
            <BreakdownCard title="Desglose por Estado" values={result?.status_breakdown ?? {}} />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MetricCard({ label, value, tone }: { label: string; value: number | string; tone: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><p className="text-sm font-medium text-slate-500">{label}</p><p className={`mt-1 text-3xl font-bold ${tone}`}>{value}</p></div>;
}

function BreakdownCard({ title, values }: { title: string; values: Record<string, number> }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm"><h3 className="mb-4 text-lg font-bold text-slate-800">{title}</h3><div className="space-y-3">{Object.entries(values).map(([label, count]) => <div key={label} className="flex items-center justify-between border-b border-slate-100 pb-2"><span className="font-medium text-slate-600">{label}</span><span className="rounded-md bg-slate-100 px-2.5 py-1 text-sm font-semibold text-slate-800">{count}</span></div>)}</div></div>;
}

function LoadingBlock({ label }: { label: string }) {
  return <div className="flex items-center gap-3 rounded-lg bg-blue-50 p-3 text-sm text-blue-700"><span className="h-4 w-4 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />{label}</div>;
}

function ErrorBlock({ message, onRetry, disabled }: { message: string; onRetry: () => void | Promise<void>; disabled?: boolean }) {
  return <div role="alert" className="flex flex-col gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 sm:flex-row sm:items-center sm:justify-between"><span>{message}</span><button type="button" onClick={() => { void onRetry(); }} disabled={disabled} className="rounded-md border border-red-300 px-3 py-1.5 font-semibold text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60">Reintentar</button></div>;
}