"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ApiError } from "@/lib/api";
import { computeStockIndex, createOutboundOrder, getOrders, getProducts, InventoryOrder, SKUProduct } from "@/lib/inventory";
import { track, withRequestId } from "@/lib/telemetry";
import { inventoryProperties, toExitType } from "@/lib/telemetry-mappers";
import { useOrderFormTelemetry } from "@/components/TelemetryProvider";

export default function OutboundOrderPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialSkuId = searchParams.get("sku_id");

  const [products, setProducts] = useState<SKUProduct[]>([]);
  const [orders, setOrders] = useState<InventoryOrder[]>([]);
  const [selectedSkuId, setSelectedSkuId] = useState<string>(initialSkuId || "");
  const [warehouse, setWarehouse] = useState<string>("Los Angeles");
  const [quantity, setQuantity] = useState<number>(1);
  const [exitType, setExitType] = useState<string>("B2C Order");
  const [trackingNumber, setTrackingNumber] = useState<string>("");
  
  const [loading, setLoading] = useState<boolean>(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const { touchField, resetForm } = useOrderFormTelemetry("outbound");

  const selectedProduct = useMemo(
    () => products.find((p) => p.id.toString() === selectedSkuId),
    [products, selectedSkuId],
  );
  // Evita recorrer miles de movimientos en cada tecla: O(n) solo al cambiar orders.
  const stockIndex = useMemo(() => computeStockIndex(orders), [orders]);
  const currentStock = selectedProduct
    ? stockIndex.get(`${selectedProduct.sku}|${warehouse}`) ?? 0
    : 0;
  const isStockExceeded = quantity > currentStock;

  useEffect(() => {
    Promise.all([getProducts(), getOrders()])
      .then(([data, movements]) => {
        setProducts(data);
        setOrders(movements);
        if (!initialSkuId && data.length > 0) {
          setSelectedSkuId(data[0].id.toString());
        }
      })
      .catch((err) => setErrorMsg(err.message));
  }, [initialSkuId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const validationProperties = selectedProduct
      ? inventoryProperties(selectedProduct, warehouse, quantity, { quantityOptional: true })
      : null;
    if (isStockExceeded) {
      setErrorMsg(`No hay suficiente stock. Disponible: ${currentStock} un.`);
      if (validationProperties) {
        track("outbound_order_validation_failed", {
          ...validationProperties,
          failure_reason: "insufficient_stock",
          validation_source: "client",
        });
      }
      return;
    }

    setLoading(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      const payload = {
        sku_id: parseInt(selectedSkuId, 10),
        warehouse,
        quantity: Number(quantity),
        exit_type: exitType,
        tracking_number: trackingNumber || undefined,
      };
      let created: { id: number };
      try {
        created = await createOutboundOrder(payload);
      } catch (error: unknown) {
        // Acción irreversible (BRIEFING §5.2): por encima del umbral la API responde 409
        // y la salida solo se registra si la persona lo confirma de forma explícita.
        if (!(error instanceof ApiError) || error.status !== 409) throw error;
        if (!window.confirm(`${error.message}\n\n¿Confirmas que quieres registrar este despacho?`)) {
          setErrorMsg("Despacho de alto valor cancelado: no se ha registrado ninguna salida.");
          return;
        }
        created = await createOutboundOrder({ ...payload, confirm_high_value: true });
      }
      const { id } = created;
      resetForm();
      const properties = selectedProduct ? inventoryProperties(selectedProduct, warehouse, quantity) : null;
      const exit_type = toExitType(exitType);
      const hasOrderId = Number.isSafeInteger(id) && id > 0;
      if (properties && exit_type && hasOrderId) {
        track("outbound_order_created", { ...properties, order_id: id, exit_type });
      }

      setSuccessMsg("¡Orden de salida registrada con éxito!");
      setQuantity(1);
      setTrackingNumber("");

      // Actualizar el stock por almacén tras registrar el movimiento.
      await getOrders().then((movements) => {
        setOrders(movements);
        if (selectedProduct && properties && hasOrderId && currentStock >= 50) {
          const refreshedStock = computeStockIndex(movements).get(`${selectedProduct.sku}|${warehouse}`) ?? 0;
          if (refreshedStock < 50) {
            track("stock_threshold_triggered", {
              ...properties, quantity: refreshedStock, min_threshold: 50, threshold_source: "global_default", trigger_order_id: id,
            });
          }
        }
      }, () => setErrorMsg("La salida se registró, pero no se pudo actualizar el stock."));
    } catch (error: unknown) {
      if (error instanceof ApiError && validationProperties) {
        const failure_reason = error.status === 400 ? "insufficient_stock"
          : error.status === 404 ? "sku_not_found"
          : error.status === 422 ? "schema_invalid" : null;
        if (failure_reason) {
          const report = () => track("outbound_order_validation_failed", {
            ...validationProperties, failure_reason, validation_source: "api",
          });
          if (error.requestId) withRequestId(error.requestId, report);
          else report();
        }
      }
      if (error instanceof ApiError && error.status === 400) {
        setErrorMsg(`La API rechazó la salida (HTTP 400): ${error.message}`);
      } else {
        setErrorMsg(error instanceof Error ? error.message : "Error al procesar la salida de inventario.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto p-6 space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold text-gray-900">Registrar Orden de Salida (Outbound)</h1>
        <button
          onClick={() => router.push("/inventory/products")}
          className="text-sm text-gray-600 hover:text-gray-900 underline"
        >
          Volver a Productos
        </button>
      </div>

      {successMsg && (
        <div className="p-4 bg-green-50 border border-green-200 text-green-700 rounded-md font-medium">
          {successMsg}
        </div>
      )}

      {errorMsg && (
        <div role="alert" className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-md font-medium">
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
            className="w-full border border-gray-300 p-2 rounded-md focus:ring-blue-500 focus:border-blue-500"
            required
          >
            {products.map((p) => (
              <option key={p.id} value={p.id}>
                {p.sku} - {p.name} ({p.client_name})
              </option>
            ))}
          </select>
        </div>

        {/* Muestreo reactivo del stock disponible antes de enviar */}
        {selectedProduct && (
          <div className={`p-3 rounded-md text-sm font-semibold flex justify-between items-center ${
            currentStock > 0 ? "bg-blue-50 text-blue-800" : "bg-red-50 text-red-800"
          }`}>
            <span>Stock disponible actual:</span>
            <span className="text-base font-bold">{currentStock} unidades</span>
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Almacén de Origen</label>
          <select
            name="warehouse"
            value={warehouse}
            onChange={(e) => setWarehouse(e.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="Los Angeles">Los Angeles (EE.UU.)</option>
            <option value="Zaragoza">Zaragoza (España)</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Tipo de Salida (Exit Type)</label>
          <select
            name="exit_type"
            value={exitType}
            onChange={(e) => setExitType(e.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="B2C Order">B2C Order (Envío a Cliente Final)</option>
            <option value="B2B Transfer">B2B Transfer (Transferencia)</option>
            <option value="Return / Damaged">Devolución / Producto Dañado</option>
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Número de Seguimiento / Tracking (Opcional)</label>
          <input
            name="tracking_number"
            type="text"
            placeholder="Ej. UPS-1Z9999999999"
            value={trackingNumber}
            onChange={(e) => setTrackingNumber(e.target.value)}
            className="w-full border border-gray-300 p-2 rounded-md focus:ring-blue-500 focus:border-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Cantidad a Retirar</label>
          <input
            name="quantity"
            type="number"
            min="1"
            value={quantity}
            onChange={(e) => setQuantity(parseInt(e.target.value, 10) || 1)}
            className={`w-full border p-2 rounded-md focus:ring-blue-500 ${
              isStockExceeded ? "border-red-500 bg-red-50 text-red-900" : "border-gray-300"
            }`}
            required
          />
          {isStockExceeded && (
            <p className="text-xs text-red-600 mt-1 font-semibold">
              ⚠️ La cantidad introducida ({quantity}) supera el stock disponible ({currentStock}).
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-md transition disabled:opacity-50"
        >
          {loading ? "Procesando..." : "Guardar Salida de Stock"}
        </button>
      </form>
    </div>
  );
}
