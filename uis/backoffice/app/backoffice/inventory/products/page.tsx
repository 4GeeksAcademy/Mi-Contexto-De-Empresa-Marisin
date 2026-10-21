"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getAccessToken } from "../../../../../application/lib/auth";
import { InventoryApiError, inventoryApi, type Product } from "../../../../lib/inventory";
import "./products.css";

function stockStatus(stock: number) {
  // Umbral operativo inicial: <= 0 sin stock; 1-10 stock bajo; > 10 saludable.
  if (stock <= 0) return { label: "Sin stock", className: "empty" };
  if (stock <= 10) return { label: "Stock bajo", className: "low" };
  return { label: "Stock saludable", className: "healthy" };
}

export default function InventoryProductsPage() {
  const router = useRouter();
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);
  const [authorized, setAuthorized] = useState(false);
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

    async function loadProducts() {
      try {
        await inventoryApi.verifySession();
        if (!active) return;
        const result = await inventoryApi.listProducts();
        if (active) setProducts(result);
      } catch (requestError) {
        if (!active) return;
        if (requestError instanceof InventoryApiError && requestError.status === 401) {
          setAuthorized(false);
          router.replace("/login");
          return;
        }
        const message = requestError instanceof Error ? requestError.message.trim() : "";
        setError(!message || message.startsWith("{") || message.startsWith("[")
          ? "No se pudo cargar el inventario. Int\u00e9ntalo de nuevo."
          : message);
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadProducts();
    return () => { active = false; };
  }, [router, revision]);

  if (!authorized) return null;

  return (
    <main className="inventory-products">
      <header className="inventory-products-header">
        <div>
          <p className="inventory-products-brand">TrackFlow / Operaciones de Almac&eacute;n</p>
          <h1>Productos y stock</h1>
          <p>Inventario global de Los &Aacute;ngeles y Zaragoza</p>
        </div>
        <button type="button" disabled={loading} onClick={() => setRevision(value => value + 1)}>
          {loading ? "Actualizando..." : "Actualizar"}
        </button>
      </header>

      <section aria-label="Productos" aria-busy={loading}>
        {loading ? (
          <p role="status" className="inventory-products-status">Cargando productos...</p>
        ) : error ? (
          <div role="alert" className="inventory-products-error">
            <p>{error}</p>
            <button type="button" onClick={() => setRevision(value => value + 1)}>Reintentar</button>
          </div>
        ) : products.length === 0 ? (
          <p role="status" className="inventory-products-status">No hay productos registrados.</p>
        ) : (
          <div className="inventory-products-scroll" role="region" aria-label="Tabla de productos" tabIndex={0}>
            <table>
              <caption>Existencias globales por SKU</caption>
              <thead>
                <tr>
                  <th scope="col">ID</th>
                  <th scope="col">SKU</th>
                  <th scope="col">Producto</th>
                  <th scope="col">Stock actual</th>
                  <th scope="col">Estado</th>
                  <th scope="col">Movimientos</th>
                </tr>
              </thead>
              <tbody>
                {products.map(product => {
                  const status = stockStatus(product.current_stock);
                  return (
                    <tr key={product.id}>
                      <td>{product.id}</td>
                      <th scope="row">{product.sku}</th>
                      <td>{product.name}</td>
                      <td className="inventory-products-quantity">{product.current_stock}</td>
                      <td><span className={`inventory-stock inventory-stock-${status.className}`}>{status.label}</span></td>
                      <td>
                        <div className="inventory-products-actions">
                          <Link href={`/backoffice/inventory/orders/inbound?product_id=${product.id}`} aria-label={`Registrar entrada de ${product.sku}`}>Entrada</Link>
                          <Link href={`/backoffice/inventory/orders/outbound?product_id=${product.id}`} aria-label={`Registrar salida de ${product.sku}`}>Salida</Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}