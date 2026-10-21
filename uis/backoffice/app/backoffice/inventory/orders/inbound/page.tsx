"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { getAccessToken } from "../../../../../../application/lib/auth";
import { InventoryApiError, inventoryApi, type Product } from "../../../../../lib/inventory";
import "../../products/products.css";
import "./inbound.css";

function requestMessage(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message.trim() : "";
  return !message || message.startsWith("{") || message.startsWith("[") ? fallback : message;
}

export default function InboundOrderPage() {
  const router = useRouter();
  const [authorized, setAuthorized] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [quantity, setQuantity] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
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
        if (!active) return;
        setProducts(result);
        const selected = new URLSearchParams(window.location.search).get("product_id");
        if (result.some(product => String(product.id) === selected)) setProductId(selected!);
      } catch (requestError) {
        if (!active) return;
        if (requestError instanceof InventoryApiError && requestError.status === 401) {
          setAuthorized(false);
          router.replace("/login");
          return;
        }
        setError(requestMessage(requestError, "No se pudieron cargar los productos."));
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadProducts();
    return () => { active = false; };
  }, [router, revision]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || loading) return;
    if (!getAccessToken()?.trim()) {
      setAuthorized(false);
      router.replace("/login");
      return;
    }
    setError("");
    setSuccess("");

    const product = products.find(item => String(item.id) === productId);
    const units = Number(quantity);
    if (!product || !["Los Angeles", "Zaragoza"].includes(warehouse) || !Number.isSafeInteger(units) || units <= 0) {
      setError("Selecciona un producto, un almac\u00e9n y una cantidad entera mayor que cero.");
      return;
    }

    setSaving(true);
    try {
      await inventoryApi.createInboundOrder({ product_id: product.id, warehouse, quantity: units });
      setProductId("");
      setWarehouse("");
      setQuantity("");
      setSuccess("Entrada de mercanc\u00eda registrada correctamente.");
    } catch (requestError) {
      if (requestError instanceof InventoryApiError && requestError.status === 401) {
        setAuthorized(false);
        router.replace("/login");
        return;
      }
      setError(requestMessage(requestError, "No se pudo registrar la entrada de mercanc\u00eda. Int\u00e9ntalo de nuevo."));
    } finally {
      setSaving(false);
    }
  }

  if (!authorized) return null;

  return (
    <main className="inventory-products inventory-inbound">
      <header className="inventory-products-header">
        <div>
          <p className="inventory-products-brand">TrackFlow / Operaciones de Almac&eacute;n</p>
          <h1>Orden de entrada</h1>
        </div>
        <Link href="/backoffice/inventory/products">Volver a productos</Link>
      </header>

      {loading && <p role="status">Cargando productos...</p>}
      {error && (
        <div role="alert" className="inventory-products-error">
          <p>{error}</p>
          {!loading && products.length === 0 && (
            <button type="button" onClick={() => setRevision(value => value + 1)}>Reintentar</button>
          )}
        </div>
      )}
      {success && <p role="status" className="inventory-inbound-success">{success}</p>}
      {!loading && !error && products.length === 0 && <p role="status">No hay productos registrados.</p>}

      <form onSubmit={handleSubmit} aria-label="Registrar entrada de mercanc&iacute;a" aria-busy={saving}>
        <fieldset disabled={loading || saving || products.length === 0}>
          <legend>Recepci&oacute;n de mercanc&iacute;a</legend>
          <label htmlFor="inbound-product">Producto</label>
          <select id="inbound-product" name="product" required value={productId} onChange={event => setProductId(event.target.value)}>
            <option value="">Selecciona un producto</option>
            {products.map(product => <option key={product.id} value={product.id}>{product.name} ({product.sku})</option>)}
          </select>

          <label htmlFor="inbound-warehouse">Almac&eacute;n de destino</label>
          <select id="inbound-warehouse" name="warehouse" required value={warehouse} onChange={event => setWarehouse(event.target.value)}>
            <option value="">Selecciona un almac&eacute;n</option>
            <option value="Los Angeles">Los &Aacute;ngeles</option>
            <option value="Zaragoza">Zaragoza</option>
          </select>

          <label htmlFor="inbound-quantity">Cantidad (unidades)</label>
          <input id="inbound-quantity" name="quantity" type="number" min="1" step="1" max={Number.MAX_SAFE_INTEGER} required value={quantity} onChange={event => setQuantity(event.target.value)} />

          <button type="submit">{saving ? "Registrando entrada..." : "Registrar entrada"}</button>
        </fieldset>
      </form>
    </main>
  );
}