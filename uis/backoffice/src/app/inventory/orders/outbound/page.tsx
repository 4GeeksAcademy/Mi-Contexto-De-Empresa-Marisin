"use client";

import React, { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createOutboundOrder, getProducts, SKUProduct } from "@/lib/inventory";

export default function OutboundOrderPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialSkuId = searchParams.get("sku_id");

  const [products, setProducts] = useState<SKUProduct[]>([]);
  const [selectedSkuId, setSelectedSkuId] = useState<string>(initialSkuId || "");
  const [warehouse, setWarehouse] = useState<string>("Los Angeles");
  const [quantity, setQuantity] = useState<number>(1);
  const [exitType, setExitType] = useState<string>("B2C Order");
  const [trackingNumber, setTrackingNumber] = useState<string>("");
  
  const [loading, setLoading] = useState<boolean>(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Obtener producto seleccionado y su stock disponible actual
  const selectedProduct = products.find((p) => p.id.toString() === selectedSkuId);
  const currentStock = selectedProduct ? selectedProduct.current_stock : 0;
  const isStockExceeded = quantity > currentStock;

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
    if (isStockExceeded) {
      setErrorMsg(`No hay suficiente stock. Disponible: ${currentStock} un.`);
      return;
    }

    setLoading(true);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      await createOutboundOrder({
        sku_id: parseInt(selectedSkuId, 10),
        warehouse,
        quantity: Number(quantity),
        exit_type: exitType,
        tracking_number: trackingNumber || undefined,
      });
      
      setSuccessMsg("¡Orden de salida registrada con éxito!");
      setQuantity(1);
      setTrackingNumber("");

      // Actualizar la lista de productos para reflejar el nuevo stock disponible
      getProducts().then((updated) => setProducts(updated));
    } catch (err: any) {
      setErrorMsg(err.message || "Error al procesar la salida de inventario (HTTP 400).");
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
        <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-md font-medium">
          ⚠️ {errorMsg}
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-white p-6 shadow rounded-lg border border-gray-200 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Producto / SKU</label>
          <select
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
          disabled={loading || isStockExceeded}
          className="w-full bg-blue-600 hover:bg-blue-700 text-white font-medium py-2 px-4 rounded-md transition disabled:opacity-50"
        >
          {loading ? "Procesando..." : "Guardar Salida de Stock"}
        </button>
      </form>
    </div>
  );
}
