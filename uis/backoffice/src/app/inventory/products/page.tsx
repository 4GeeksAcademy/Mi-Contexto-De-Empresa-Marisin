"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useInventoryData } from "@/hooks/useInventoryData";
import { ApiError } from "@/lib/api";
import {
  computeStockIndex,
  getOrders,
  getProducts,
  requestDirectStockEdit,
  type SKUProduct,
} from "@/lib/inventory";
import { track, withRequestId } from "@/lib/telemetry";
import { inventoryProperties } from "@/lib/telemetry-mappers";

const LOW_STOCK_THRESHOLD = 50;

export default function InventoryProductsPage() {
  const { data, loading, error } = useInventoryData(getProducts);
  const products = data ?? [];
  const [editProduct, setEditProduct] = useState<SKUProduct | null>(null);
  const [editWarehouse, setEditWarehouse] = useState("Los Angeles");
  const [editQuantity, setEditQuantity] = useState(0);
  const [editBusy, setEditBusy] = useState(false);
  const [editRejected, setEditRejected] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  function openDirectEdit(product: SKUProduct) {
    setEditProduct(product);
    setEditWarehouse("Los Angeles");
    setEditQuantity(0);
    setEditRejected(false);
    setEditError(null);
  }

  async function handleDirectEdit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editProduct) return;
    const product = editProduct;
    const warehouse = editWarehouse;
    const quantity = editQuantity;
    setEditBusy(true);
    setEditRejected(false);
    setEditError(null);
    try {
      await requestDirectStockEdit(product.id, warehouse, quantity);
      setEditError("La API no rechazó el ajuste directo: revisa el endpoint de stock.");
    } catch (error: unknown) {
      if (error instanceof ApiError && [404, 405, 422].includes(error.status)) {
        if (error.status === 405) setEditRejected(true);
        else setEditError(error.message);
        const rejection_reason = `http_${error.status}`;
        const properties = inventoryProperties(product, warehouse, quantity);
        if (properties) {
          let attempted_delta: number | undefined;
          try {
            const current = computeStockIndex(await getOrders())
              .get(`${product.sku}|${warehouse}`) ?? 0;
            attempted_delta = quantity - current;
          } catch {
            attempted_delta = undefined;
          }
          const report = () => track("direct_stock_edit_rejected", {
            ...properties, rejection_reason, attempted_delta,
          });
          if (error.requestId) withRequestId(error.requestId, report);
          else report();
        }
      } else {
        setEditError(error instanceof Error ? error.message : "No se pudo enviar el ajuste.");
      }
    } finally {
      setEditBusy(false);
    }
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-md">
          <p className="font-semibold">Error al cargar productos:</p>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Gestión de Inventario (SKUs)</h1>
          <p className="text-sm text-gray-500">Visibilidad global de productos de TrackFlow</p>
        </div>
        <div className="space-x-3">
          <Link
            href="/inventory/orders/inbound"
            className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-md font-medium text-sm transition"
          >
            + Registrar Entrada
          </Link>
          <Link
            href="/inventory/orders/outbound"
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-md font-medium text-sm transition"
          >
            - Registrar Salida
          </Link>
        </div>
      </div>

      {editProduct && (
        <form
          onSubmit={handleDirectEdit}
          className="bg-white p-4 shadow rounded-lg border border-gray-200 space-y-3"
        >
          <div className="flex justify-between items-center">
            <h2 className="text-lg font-semibold text-gray-900">
              Ajustar stock de {editProduct.sku}
            </h2>
            <button
              type="button"
              onClick={() => setEditProduct(null)}
              className="text-sm text-gray-600 hover:text-gray-900 underline"
            >
              Cerrar
            </button>
          </div>
          <div className="flex flex-wrap gap-3 items-end">
            <label className="text-sm font-medium text-gray-700">
              Almacén
              <select
                value={editWarehouse}
                onChange={(e) => setEditWarehouse(e.target.value)}
                className="mt-1 block border border-gray-300 p-2 rounded-md"
              >
                <option value="Los Angeles">Los Angeles (EE.UU.)</option>
                <option value="Zaragoza">Zaragoza (España)</option>
              </select>
            </label>
            <label className="text-sm font-medium text-gray-700">
              Nuevo stock
              <input
                type="number"
                min={0}
                step={1}
                value={editQuantity}
                onChange={(e) => setEditQuantity(Number(e.target.value))}
                className="mt-1 block w-32 border border-gray-300 p-2 rounded-md"
                required
              />
            </label>
            <button
              type="submit"
              disabled={editBusy}
              className="bg-gray-800 hover:bg-gray-900 text-white px-4 py-2 rounded-md font-medium text-sm disabled:opacity-50"
            >
              {editBusy ? "Enviando..." : "Guardar ajuste"}
            </button>
          </div>
          {editRejected && (
            <div role="alert" className="p-3 bg-amber-50 border border-amber-200 text-amber-800 rounded-md text-sm">
              El stock solo se modifica con órdenes de entrada o salida.{" "}
              <Link href={`/inventory/orders/inbound?sku_id=${editProduct.id}`} className="underline font-medium">
                Registrar entrada
              </Link>{" "}
              o{" "}
              <Link href={`/inventory/orders/outbound?sku_id=${editProduct.id}`} className="underline font-medium">
                Registrar salida
              </Link>
              .
            </div>
          )}
          {editError && (
            <p role="alert" className="text-sm text-red-700">{editError}</p>
          )}
        </form>
      )}

      <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">SKU</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Producto</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cliente B2B</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Categoría</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Referencia</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Stock Actual</th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Acciones</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {loading
              ? Array.from({ length: 5 }, (_, index) => (
                  <tr key={`skeleton-${index}`} className="h-14">
                    <td className="px-6 py-4"><div className="h-4 w-16 rounded bg-gray-200" /></td>
                    <td className="px-6 py-4"><div className="h-4 w-32 rounded bg-gray-200" /></td>
                    <td className="px-6 py-4"><div className="h-4 w-28 rounded bg-gray-200" /></td>
                    <td className="px-6 py-4"><div className="h-4 w-24 rounded bg-gray-200" /></td>
                    <td className="px-6 py-4"><div className="h-4 w-24 rounded bg-gray-200" /></td>
                    <td className="px-6 py-4"><div className="h-4 w-20 rounded bg-gray-200" /></td>
                    <td className="px-6 py-4"><div className="h-4 w-14 rounded bg-gray-200" /></td>
                  </tr>
                ))
              : products.map((item) => {
              const isLowStock = item.current_stock < LOW_STOCK_THRESHOLD;
              return (
                <tr key={item.id} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-semibold text-gray-900">
                    {item.sku}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-800">{item.name}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{item.client_name}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{item.category}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{item.reference}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm">
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                        isLowStock
                          ? "bg-red-100 text-red-800"
                          : "bg-green-100 text-green-800"
                      }`}
                    >
                      {item.current_stock} un. {isLowStock ? "(Stock Bajo)" : "(Saludable)"}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-2">
                    <Link
                      href={`/inventory/orders/inbound?sku_id=${item.id}`}
                      className="text-green-600 hover:text-green-900"
                    >
                      Entrada
                    </Link>
                    <span className="text-gray-300">|</span>
                    <Link
                      href={`/inventory/orders/outbound?sku_id=${item.id}`}
                      className="text-blue-600 hover:text-blue-900"
                    >
                      Salida
                    </Link>
                    <span className="text-gray-300">|</span>
                    <button
                      type="button"
                      onClick={() => openDirectEdit(item)}
                      className="text-gray-600 hover:text-gray-900"
                    >
                      Ajustar stock
                    </button>
                  </td>
                </tr>
              );
              })}
          </tbody>
        </table>
      </div>
    </div>
  );
}