"use client";

import { useInventoryData } from "@/hooks/useInventoryData";
import { getOrders } from "@/lib/inventory";

export default function InventoryOrdersHistoryPage() {
  const { data, loading, error } = useInventoryData(getOrders);
  const orders = data ?? [];

  if (loading) return <div className="p-6 text-gray-600">Cargando historial de órdenes...</div>;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Historial de Órdenes de Inventario</h1>
        <p className="text-sm text-gray-500">Registro de todas las entradas y salidas realizadas en TrackFlow</p>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-md">
          {error}
        </div>
      )}

      <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tipo</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Producto (SKU)</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Almacén</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Cantidad</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Fecha</th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Usuario</th>
            </tr>
          </thead>
          <tbody className="bg-white divide-y divide-gray-200">
            {orders.map((order) => {
              const isInbound = order.order_type === "inbound";
              return (
                <tr key={`${order.order_type}-${order.id}`} className="hover:bg-gray-50">
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-semibold">
                    <span
                      className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                        isInbound
                          ? "bg-green-100 text-green-800"
                          : "bg-blue-100 text-blue-800"
                      }`}
                    >
                      {isInbound ? "Entrada (Inbound)" : "Salida (Outbound)"}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                    {order.product?.name || "SKU"} ({order.product?.sku})
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">{order.warehouse}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-bold text-gray-800">
                    {isInbound ? `+${order.quantity}` : `-${order.quantity}`} un.
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {new Date(order.created_at).toLocaleString("es-ES")}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {order.user_uuid}
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
