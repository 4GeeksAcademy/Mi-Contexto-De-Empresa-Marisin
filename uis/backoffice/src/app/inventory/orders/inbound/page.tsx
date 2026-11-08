"use client";

import React, { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createInboundOrder, getProducts, SKUProduct } from "@/lib/inventory";

export default function InboundOrderPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialSkuId = searchParams.get("sku_id");

  const [products, setProducts] = useState<SKUProduct[]>([]);
  const [selectedSkuId, setSelectedSkuId] = useState<string>(initialSkuId || "");
  const [warehouse, setWarehouse] = useState<string>("Los Angeles");
  const [quantity, setQuantity] = useState<number>(1);
  const [loading, setLoading] = useState<boolean>(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

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

    try {
      await createInboundOrder({
        sku_id: parseInt(selectedSkuId, 10),
        warehouse,
        quantity: Number(quantity),
      });
      setSuccessMsg("¡Orden de entrada registrada con éxito!");
      setQuantity(1);
    } catch (err: any) {
      setErrorMsg(err.message || "Error al procesar la entrada de stock.");
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

      <form onSubmit={handleSubmit} className="bg-white p-6 shadow rounded-lg border border-gray-200 space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Producto / SKU</label>
          <select
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
