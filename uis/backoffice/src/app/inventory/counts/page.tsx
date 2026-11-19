"use client";

import { useEffect, useState, type FormEvent } from "react";
import {
  computeStockIndex,
  getOrders,
  getProducts,
  type SKUProduct,
} from "@/lib/inventory";
import { track } from "@/lib/telemetry";
import { inventoryProperties } from "@/lib/telemetry-mappers";

type CountResult = {
  sku: string;
  warehouse: string;
  systemQuantity: number;
  countedQuantity: number;
};

// Conteo físico (D29): compara lo contado con el stock del sistema y registra
// la discrepancia como telemetría. No persiste nada en la base de datos.
export default function PhysicalCountPage() {
  const [products, setProducts] = useState<SKUProduct[]>([]);
  const [selectedSkuId, setSelectedSkuId] = useState("");
  const [warehouse, setWarehouse] = useState("Los Angeles");
  const [countedQuantity, setCountedQuantity] = useState(0);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CountResult | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    getProducts()
      .then((data) => {
        setProducts(data);
        if (data.length > 0) setSelectedSkuId(data[0].id.toString());
      })
      .catch((err: unknown) =>
        setErrorMsg(err instanceof Error ? err.message : "No se pudieron cargar los productos."),
      );
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const product = products.find((p) => p.id.toString() === selectedSkuId);
    if (!product || !Number.isSafeInteger(countedQuantity) || countedQuantity < 0) return;
    setLoading(true);
    setErrorMsg(null);
    setResult(null);
    try {
      // Se recalcula con los movimientos actuales para comparar con el dato más reciente.
      const systemQuantity = computeStockIndex(await getOrders())
        .get(`${product.sku}|${warehouse}`) ?? 0;
      const difference = countedQuantity - systemQuantity;
      setResult({ sku: product.sku, warehouse, systemQuantity, countedQuantity });
      if (difference !== 0) {
        const properties = inventoryProperties(product, warehouse, difference);
        if (properties) {
          track("inventory_discrepancy_detected", {
            ...properties,
            system_quantity: systemQuantity,
            counted_quantity: countedQuantity,
            detection_source: "physical_count",
          });
        }
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : "No se pudo calcular el stock del sistema.");
    } finally {
      setLoading(false);
    }
  }

  const difference = result ? result.countedQuantity - result.systemQuantity : 0;

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Conteo físico de inventario</h1>
        <p className="text-sm text-gray-500">
          Compara las unidades contadas en el almacén con el stock que registra el sistema.
        </p>
      </div>

      {errorMsg && (
        <div role="alert" className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-md">
          {errorMsg}
        </div>
      )}

      {result && (
        <div
          role="status"
          className={`p-4 rounded-md border font-medium ${
            difference === 0
              ? "bg-green-50 border-green-200 text-green-700"
              : "bg-amber-50 border-amber-200 text-amber-800"
          }`}
        >
          {difference === 0
            ? `Coincide: ${result.sku} en ${result.warehouse} tiene ${result.systemQuantity} unidades.`
            : `Discrepancia de ${difference > 0 ? "+" : ""}${difference} unidades en ${result.sku} (${result.warehouse}): sistema ${result.systemQuantity}, contado ${result.countedQuantity}.`}
        </div>
      )}

      <form
        onSubmit={handleSubmit}
        className="bg-white p-6 shadow rounded-lg border border-gray-200 space-y-4"
      >
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Producto / SKU</label>
          <select
            value={selectedSkuId}
            onChange={(e) => setSelectedSkuId(e.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md"
            required
          >
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.sku} - {p.name} ({p.client_name})
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Almacén</label>
          <select
            value={warehouse}
            onChange={(e) => setWarehouse(e.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md"
          >
            <option value="Los Angeles">Los Angeles (EE.UU.)</option>
            <option value="Zaragoza">Zaragoza (España)</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Cantidad contada</label>
          <input
            type="number"
            min={0}
            step={1}
            value={countedQuantity}
            onChange={(e) => setCountedQuantity(Number(e.target.value))}
            className="w-full border border-gray-300 p-2 rounded-md"
            required
          />
        </div>

        <button
          type="submit"
          disabled={loading || products.length === 0}
          className="w-full bg-gray-800 hover:bg-gray-900 text-white font-medium py-2 px-4 rounded-md disabled:opacity-50"
        >
          {loading ? "Comparando..." : "Registrar conteo"}
        </button>
      </form>
    </div>
  );
}
