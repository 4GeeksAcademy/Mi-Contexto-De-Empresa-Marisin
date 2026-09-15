"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  clearSessionAndRedirect,
  protectedFetch,
  UnauthorizedError,
} from "../api";

type Supplier = {
  id: string;
  name: string;
  country: string;
  categories: string[];
  rate_usd: number;
  status: string;
};

export default function SuppliersPage() {
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let isCurrent = true;

    async function loadSuppliers() {
      try {
        const response = await protectedFetch("/suppliers");
        if (!response.ok) {
          throw new Error("No se pudo cargar el directorio de proveedores.");
        }

        const data = (await response.json()) as Supplier[];
        if (isCurrent) {
          setSuppliers(data);
        }
      } catch (requestError) {
        if (requestError instanceof UnauthorizedError) {
          return;
        }

        if (isCurrent) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "No se pudo conectar con el servidor.",
          );
        }
      } finally {
        if (isCurrent) {
          setLoading(false);
        }
      }
    }

    void loadSuppliers();

    return () => {
      isCurrent = false;
    };
  }, []);

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-12 text-white">
      <div className="mx-auto max-w-5xl">
        <header className="mb-8 flex items-start justify-between gap-4">
          <div>
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-cyan-400">
              TrackFlow
            </p>
            <h1 className="text-3xl font-bold tracking-tight">Proveedores</h1>
            <p className="mt-2 text-sm text-slate-400">
              Directorio de proveedores disponibles.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <Link
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition hover:border-cyan-400 hover:text-cyan-300"
              href="/account/profile"
            >
              Mi cuenta
            </Link>
            <button
              className="rounded-lg border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition hover:border-red-400 hover:text-red-300"
              onClick={clearSessionAndRedirect}
              type="button"
            >
              Cerrar sesión
            </button>
          </div>
        </header>

        {loading && <p className="text-sm text-slate-400">Cargando proveedores...</p>}

        {error && (
          <p className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </p>
        )}

        {!loading && !error && (
          <div className="overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full min-w-160 text-left text-sm">
              <thead className="bg-slate-900 text-slate-300">
                <tr>
                  <th className="px-4 py-3 font-medium">Proveedor</th>
                  <th className="px-4 py-3 font-medium">País</th>
                  <th className="px-4 py-3 font-medium">Categorías</th>
                  <th className="px-4 py-3 font-medium">Tarifa</th>
                  <th className="px-4 py-3 font-medium">Estado</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800 bg-slate-900/50">
                {suppliers.map((supplier) => (
                  <tr key={supplier.id}>
                    <td className="px-4 py-3 font-medium">{supplier.name}</td>
                    <td className="px-4 py-3 text-slate-300">{supplier.country}</td>
                    <td className="px-4 py-3 text-slate-300">
                      {supplier.categories.join(", ")}
                    </td>
                    <td className="px-4 py-3 text-slate-300">${supplier.rate_usd}</td>
                    <td className="px-4 py-3 text-slate-300">{supplier.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}