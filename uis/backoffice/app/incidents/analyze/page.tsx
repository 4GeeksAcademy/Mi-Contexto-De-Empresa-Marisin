'use client';

import React, { useState } from 'react';

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

export default function IncidentsAnalyzePage() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
      setError(null);
    }
  };

  const handleAnalyze = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError('Por favor, selecciona un fichero CSV.');
      return;
    }

    setLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append('file', file);

    try {
      // Apunta a la ruta del endpoint que creamos en services/api
      const res = await fetch('/api/incidents/analyze', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.error || 'Error al procesar el fichero.');
      }

      setResult(data);
    } catch (err: any) {
      setError(err.message || 'Error de conexión con el servidor.');
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = () => {
    // Apunta al endpoint GET de exportación
    window.location.href = '/api/incidents/results/export';
  };

  return (
    <div className="p-8 max-w-6xl mx-auto font-sans">
      <h1 className="text-3xl font-bold mb-2 text-slate-800">Análisis de Incidencias — TrackFlow</h1>
      <p className="text-slate-600 mb-6">Sube el fichero CSV de la empresa para validar registros y ver las métricas operativas.</p>

      {/* Formulario de Carga */}
      <div className="bg-white p-6 rounded-xl shadow-sm border border-slate-200 mb-8">
        <form onSubmit={handleAnalyze} className="flex flex-col gap-4">
          <div className="border-2 border-dashed border-slate-300 rounded-lg p-6 text-center hover:border-blue-500 transition-colors cursor-pointer">
            <input 
              type="file" 
              accept=".csv" 
              onChange={handleFileChange} 
              className="block w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
            />
            <p className="mt-2 text-sm text-slate-500">Selecciona o arrastra tu fichero CSV corporativo</p>
          </div>

          {error && <div className="p-3 bg-red-50 border border-red-200 text-red-700 rounded-lg text-sm">{error}</div>}

          <button 
            type="submit" 
            disabled={loading}
            className="bg-blue-600 text-white font-medium py-2.5 px-4 rounded-lg hover:bg-blue-700 transition-colors disabled:bg-slate-400"
          >
            {loading ? 'Analizando registros...' : 'Ejecutar Análisis'}
          </button>
        </form>
      </div>

      {/* Resultados y Métricas */}
      {result && (
        <div className="space-y-6">
          <div className="flex justify-between items-center">
            <h2 className="text-2xl font-bold text-slate-800">Resultados del Análisis</h2>
            <button 
              onClick={handleDownload}
              className="bg-emerald-600 text-white font-medium py-2 px-4 rounded-lg hover:bg-emerald-700 transition-colors text-sm flex items-center gap-2"
            >
              📥 Descargar Resultados en CSV
            </button>
          </div>

          {/* Métricas Generales */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500 font-medium">Total Elementos</p>
              <p className="text-3xl font-bold text-slate-800 mt-1">{result.total_elements}</p>
            </div>
            <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500 font-medium">Registros Válidos</p>
              <p className="text-3xl font-bold text-emerald-600 mt-1">{result.valid_records}</p>
            </div>
            <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500 font-medium">Registros Inválidos</p>
              <p className="text-3xl font-bold text-red-600 mt-1">{result.invalid_records}</p>
            </div>
            <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
              <p className="text-sm text-slate-500 font-medium">Satisfacción Promedio</p>
              <p className="text-3xl font-bold text-blue-600 mt-1">{result.avg_satisfaction} / 5</p>
            </div>
          </div>

          {/* Alerta de Registros Inválidos */}
          {result.invalid_records > 0 && (
            <div className="bg-amber-50 border border-amber-200 p-4 rounded-xl text-amber-800 text-sm">
              <p className="font-semibold mb-1">⚠️ Atención: Se han detectado registros inválidos en el fichero:</p>
              <ul className="list-disc list-inside space-y-1">
                <li>Campos vacíos o faltantes: <strong>{result.invalid_reasons.missing_fields}</strong></li>
                <li>Categorías no reconocidas: <strong>{result.invalid_reasons.invalid_category}</strong></li>
                <li>Estados no reconocidos: <strong>{result.invalid_reasons.invalid_status}</strong></li>
              </ul>
            </div>
          )}

          {/* Desgloses (Categorías y Estados) */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <h3 className="text-lg font-bold text-slate-800 mb-4">Desglose por Categoría</h3>
              <div className="space-y-3">
                {Object.entries(result.category_breakdown).map(([cat, count]) => (
                  <div key={cat} className="flex justify-between items-center border-b border-slate-100 pb-2">
                    <span className="text-slate-600 font-medium">{cat}</span>
                    <span className="bg-slate-100 text-slate-800 px-2.5 py-1 rounded-md text-sm font-semibold">{count}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
              <h3 className="text-lg font-bold text-slate-800 mb-4">Desglose por Estado</h3>
              <div className="space-y-3">
                {Object.entries(result.status_breakdown).map(([status, count]) => (
                  <div key={status} className="flex justify-between items-center border-b border-slate-100 pb-2">
                    <span className="text-slate-600 font-medium">{status}</span>
                    <span className="bg-slate-100 text-slate-800 px-2.5 py-1 rounded-md text-sm font-semibold">{count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}