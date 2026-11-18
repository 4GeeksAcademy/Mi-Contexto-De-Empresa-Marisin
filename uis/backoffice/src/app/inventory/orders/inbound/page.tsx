"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/api";
import { computeStockIndex, createInboundOrder, getOrders, getProducts, InventoryOrder, SKUProduct } from "@/lib/inventory";
import { track, withRequestId } from "@/lib/telemetry";
import { inventoryProperties } from "@/lib/telemetry-mappers";
import { useOrderFormTelemetry } from "@/components/TelemetryProvider";

export default function InboundOrderPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialSkuId = searchParams.get("sku_id");

  const [products, setProducts] = useState<SKUProduct[]>([]);
  const [orders, setOrders] = useState<InventoryOrder[] | null>(null);
  const [selectedSkuId, setSelectedSkuId] = useState<string>(initialSkuId || "");
  const [warehouse, setWarehouse] = useState<string>("Los Angeles");
  const [quantity, setQuantity] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const { touchField, resetForm } = useOrderFormTelemetry("inbound");
  const stockIndex = useMemo(() => orders === null ? null : computeStockIndex(orders), [orders]);

  useEffect(() => {
    let active = true;
    getOrders().then(
      (movements) => { if (active) setOrders(movements); },
      () => { if (active) setErrorMsg("No se pudo consultar el stock por almacén."); },
    );
    return () => { active = false; };
  }, []);

  useEffect(() => {
    getProducts()
      .then((data) => {
        setProducts(data);
        if (!initialSkuId && data.length > 0) {
          setSelectedSkuId(data[0].id.toString());
        }
      })
      .catch((err) => setErrorMsg(err.message));
  }, [initialSkuId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    const selectedProduct = products.find((product) => product.id.toString() === selectedSkuId);
    const stockKey = selectedProduct ? `${selectedProduct.sku}|${warehouse}` : null;
    const previousStock = stockIndex && stockKey ? stockIndex.get(stockKey) ?? 0 : null;

    try {
      const { id } = await createInboundOrder({
        sku_id: parseInt(selectedSkuId, 10),
        warehouse,
        quantity: Number(quantity),
      });
      resetForm();
      const properties = selectedProduct ? inventoryProperties(selectedProduct, warehouse, quantity) : null;
      const hasOrderId = Number.isSafeInteger(id) && id > 0;
      if (properties && hasOrderId) {
        track("inbound_order_created", { ...properties, order_id: id });
      }
      setSuccessMsg("¡Orden de entrada registrada con éxito!");
      setQuantity(1);
      await getOrders().then((movements) => {
        setOrders(movements);
        if (properties && hasOrderId && stockKey && previousStock !== null && previousStock < 50) {
          const refreshedStock = computeStockIndex(movements).get(stockKey) ?? 0;
          if (refreshedStock >= 50) {
            track("stock_threshold_cleared", {
              ...properties, min_threshold: 50, threshold_source: "global_default", trigger_order_id: id,
            });
          }
        }
      }, () => {
        setOrders(null);
        setErrorMsg("La entrada se registró, pero no se pudo actualizar el stock.");
      });
    } catch (error: unknown) {
      if (error instanceof ApiError && selectedProduct) {
        const failure_reason = error.status === 404 ? "sku_not_found"
          : error.status === 422 ? "schema_invalid" : null;
        const properties = inventoryProperties(selectedProduct, warehouse, quantity, { quantityOptional: true });
        if (properties && failure_reason) {
          const report = () => track("inbound_order_validation_failed", {
            ...properties, failure_reason, validation_source: "api",
          });
          if (error.requestId) withRequestId(error.requestId, report);
          else report();
        }
      }
      setErrorMsg(error instanceof Error ? error.message : "Error al procesar la entrada de stock.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-gray-900">Registrar Orden de Entrada (Inbound)</h1>
        <button
          onClick={() => router.push("/inventory/products")}
          className="text-sm text-gray-600 hover:text-gray-900 underline"
        >
          Volver a Productos
        </button>
      </div>

      {successMsg && (
        <div className="p-4 bg-green-50 border border-green-200 text-green-700 rounded-md">
          {successMsg}
        </div>
      )}

      {errorMsg && (
        <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-md">
          {errorMsg}
        </div>
      )}

      <form onSubmit={handleSubmit} onFocus={touchField} onChange={touchField} className="bg-white p-6 shadow rounded-lg border border-gray-200 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Producto / SKU</label>
          <select
            name="sku"
            value={selectedSkuId}
            onChange={(e) => setSelectedSkuId(e.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md focus:ring-green-500 focus:border-green-500"
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
          <label className="block text-sm font-medium text-gray-700 mb-1">Almacén de Destino</label>
          <select
            name="warehouse"
            value={warehouse}
            onChange={(e) => setWarehouse(e.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md focus:ring-green-500 focus:border-green-500"
          >
            <option value="Los Angeles">Los Angeles (EE.UU.)</option>
            <option value="Zaragoza">Zaragoza (España)</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Cantidad a Ingresar</label>
          <input
            name="quantity"
            type="number"
            min="1"
            value={quantity}
            onChange={(e) => setQuantity(parseInt(e.target.value, 10) || 1)}
            className="w-full border border-gray-300 p-2 rounded-md focus:ring-green-500 focus:border-green-500"
            required
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-green-600 hover:bg-green-700 text-white font-medium py-2 px-4 rounded-md transition disabled:opacity-50"
        >
          {loading ? "Registrando..." : "Guardar Entrada de Stock"}
        </button>
      </form>
    </div>
  );
}
