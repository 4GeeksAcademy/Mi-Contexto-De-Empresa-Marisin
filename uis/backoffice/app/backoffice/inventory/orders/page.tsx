"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getAccessToken } from "../../../../../application/lib/auth";
import { InventoryApiError, inventoryApi, type InventoryOrder } from "../../../../lib/inventory";
import "../products/products.css";

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Fecha no disponible"
    : new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "medium" }).format(date);
}

export default function InventoryOrdersPage() {
  const router = useRouter();
  const [authorized, setAuthorized] = useState(false);
  const [orders, setOrders] = useState<InventoryOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    let active = true;
    if (!getAccessToken()?.trim()) {
      setAuthorized(false);
      router.replace("/login");
      return;
    }
    setAuthorized(true);
    setLoading(true);
    setError("");

    async function loadOrders() {
      try {
        const result = await inventoryApi.listOrders();
        if (active) setOrders(result);
      } catch (requestError) {
        if (!active) return;
        if (requestError instanceof InventoryApiError && requestError.status === 401) {
          setAuthorized(false);
          router.replace("/login");
          return;
        }
        const message = requestError instanceof Error ? requestError.message.trim() : "";
        setError(!message || message.startsWith("{") || message.startsWith("[")
          ? "No se pudo cargar el historial de ordenes. Intentalo de nuevo."
          : message);
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadOrders();
    return () => { active = false; };
  }, [router, revision]);

  if (!authorized) return null;

  return (
    <main className="inventory-products">
      <header className="inventory-products-header">
        <div>
          <p className="inventory-products-brand">TrackFlow / Operaciones de Almac&eacute;n</p>
          <h1>Historial de &oacute;rdenes</h1>
        </div>
        <Link href="/backoffice/inventory/products">Volver a productos</Link>
        <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>
          {loading ? "Actualizando..." : "Actualizar historial"}
        </button>
      </header>

      <section aria-label="Historial de ordenes de inventario" aria-busy={loading}>
        {loading ? (
          <p role="status" className="inventory-products-status">Cargando historial...</p>
        ) : error ? (
          <div role="alert" className="inventory-products-error">
            <p>{error}</p>
            <button type="button" onClick={() => setRevision(value => value + 1)}>Reintentar</button>
          </div>
        ) : orders.length === 0 ? (
          <p role="status" className="inventory-products-status">No hay movimientos de inventario registrados.</p>
        ) : (
          <div className="inventory-products-scroll" role="region" aria-label="Tabla de movimientos de inventario" tabIndex={0}>
            <table>
              <caption>Movimientos de inventario de Los &Aacute;ngeles y Zaragoza</caption>
              <thead>
                <tr>
                  <th scope="col">Producto</th>
                  <th scope="col">SKU</th>
                  <th scope="col">Cantidad</th>
                  <th scope="col">Tipo de orden</th>
                  <th scope="col">Fecha de creaci&oacute;n</th>
                  <th scope="col">Almac&eacute;n</th>
                  <th scope="col">Responsable (user_uuid)</th>
                </tr>
              </thead>
              <tbody>
                {orders.map(order => (
                  <tr key={`${order.order_type}-${order.id}`}>
                    <th scope="row">{order.product.name}</th>
                    <td>{order.product.sku}</td>
                    <td className="inventory-products-quantity">{order.quantity}</td>
                    <td>
                      <span className={`inventory-stock inventory-stock-${order.order_type === "inbound" ? "healthy" : "low"}`}>
                        {order.order_type === "inbound" ? "Entrada" : "Salida"}
                      </span>
                    </td>
                    <td><time dateTime={order.created_at} title={order.created_at}>{formatDate(order.created_at)}</time></td>
                    <td>{order.warehouse === "Los Angeles" ? "Los \u00c1ngeles" : order.warehouse}</td>
                    <td><code>{order.user_uuid}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}