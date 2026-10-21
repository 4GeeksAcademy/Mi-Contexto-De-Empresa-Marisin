"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { getAccessToken } from "../../../../../../application/lib/auth";
import { InventoryApiError, inventoryApi, type Product } from "../../../../../lib/inventory";
import "../../products/products.css";
import "../inbound/inbound.css";

function requestMessage(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message.trim() : "";
  return !message || message.startsWith("{") || message.startsWith("[") ? fallback : message;
}

export default function OutboundOrderPage() {
  const router = useRouter();
  const [authorized, setAuthorized] = useState(false);
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState("");
  const [warehouse, setWarehouse] = useState("");
  const [quantity, setQuantity] = useState("");
  const [stock, setStock] = useState<Product | null>(null);
  const [loading, setLoading] = useState(true);
  const [stockLoading, setStockLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [stockError, setStockError] = useState("");
  const [quantityError, setQuantityError] = useState("");
  const [success, setSuccess] = useState("");
  const [listRevision, setListRevision] = useState(0);
  const [stockRevision, setStockRevision] = useState(0);

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
        const result = await inventoryApi.listProducts();
        if (!active) return;
        setProducts(result);
        const selected = new URLSearchParams(window.location.search).get("product_id");
        if (selected && result.some(product => String(product.id) === selected)) setProductId(selected);
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
  }, [router, listRevision]);

  useEffect(() => {
    if (!authorized || !productId) return;
    let active = true;
    setStock(null);
    setStockLoading(true);
    setStockError("");

    async function loadStock() {
      try {
        const product = await inventoryApi.getProduct(Number(productId));
        if (active) setStock(product);
      } catch (requestError) {
        if (!active) return;
        if (requestError instanceof InventoryApiError && requestError.status === 401) {
          setAuthorized(false);
          router.replace("/login");
          return;
        }
        setStockError(requestMessage(requestError, "No se pudo consultar el stock del producto."));
      } finally {
        if (active) setStockLoading(false);
      }
    }

    void loadStock();
    return () => { active = false; };
  }, [authorized, productId, stockRevision, router]);

  const currentProduct = stock && String(stock.id) === productId ? stock : null;
  const units = Number(quantity);
  const exceedsStock = Boolean(currentProduct && units > currentProduct.current_stock);
  const validQuantity = Number.isSafeInteger(units) && units > 0;

  function changeProduct(value: string) {
    setProductId(value);
    setStock(null);
    setQuantity("");
    setStockError("");
    setQuantityError("");
    setSuccess("");
    setError("");
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (saving || loading || stockLoading) return;
    if (!getAccessToken()?.trim()) {
      setAuthorized(false);
      router.replace("/login");
      return;
    }
    setError("");
    setQuantityError("");
    setSuccess("");
    if (!currentProduct || !products.some(product => product.id === currentProduct.id) || !["Los Angeles", "Zaragoza"].includes(warehouse)) {
      setError("Selecciona un producto con stock consultado y un almacen de origen.");
      return;
    }
    if (!validQuantity || exceedsStock) {
      setQuantityError(exceedsStock ? "La cantidad supera el stock global disponible." : "Introduce una cantidad entera mayor que cero.");
      return;
    }

    setSaving(true);
    try {
      await inventoryApi.createOutboundOrder({ product_id: currentProduct.id, warehouse, quantity: units });
      changeProduct("");
      setWarehouse("");
      setSuccess("Salida de mercanc\u00eda registrada correctamente.");
    } catch (requestError) {
      if (requestError instanceof InventoryApiError && requestError.status === 401) {
        setAuthorized(false);
        router.replace("/login");
        return;
      }
      const message = requestMessage(requestError, "No se pudo registrar la salida de mercancia. Intentalo de nuevo.");
      if (requestError instanceof InventoryApiError && requestError.status === 400) {
        setQuantityError(message);
      } else {
        setError(message);
      }
    } finally {
      setSaving(false);
    }
  }

  if (!authorized) return null;

  return (
    <main className="inventory-products">
      <header className="inventory-products-header">
        <div>
          <p className="inventory-products-brand">TrackFlow / Operaciones de Almac&eacute;n</p>
          <h1>Orden de salida</h1>
        </div>
        <Link href="/backoffice/inventory/products">Volver a productos</Link>
      </header>

      <section className="inventory-inbound" aria-label="Salida de mercancia">
        {loading && <p role="status">Cargando productos...</p>}
        {error && (
          <div role="alert" className="inventory-products-error">
            <p>{error}</p>
            {!loading && products.length === 0 && <button type="button" onClick={() => setListRevision(value => value + 1)}>Reintentar</button>}
          </div>
        )}
        {success && <p role="status" className="inventory-inbound-success">{success}</p>}
        {!loading && !error && products.length === 0 && <p role="status">No hay productos registrados.</p>}

        <form onSubmit={handleSubmit} aria-label="Registrar salida de mercancia" aria-busy={saving}>
          <fieldset disabled={loading || saving || products.length === 0}>
            <legend>Salida de mercanc&iacute;a</legend>
            <label htmlFor="outbound-product">Producto</label>
            <select id="outbound-product" name="product" required value={productId} onChange={event => changeProduct(event.target.value)}>
              <option value="">Selecciona un producto</option>
              {products.map(product => <option key={product.id} value={product.id}>{product.name} ({product.sku})</option>)}
            </select>

            <div aria-live="polite" id="outbound-stock">
              {productId && (stockLoading || (!currentProduct && !stockError)) && <p role="status">Consultando stock...</p>}
              {currentProduct && <p>Stock global disponible: <strong>{currentProduct.current_stock}</strong> unidades (Los &Aacute;ngeles y Zaragoza).</p>}
              {stockError && <p role="alert" className="inventory-stock-empty">{stockError}</p>}
              {productId && <button type="button" disabled={stockLoading} onClick={() => setStockRevision(value => value + 1)}>Actualizar stock</button>}
            </div>

            <label htmlFor="outbound-warehouse">Almac&eacute;n de origen</label>
            <select id="outbound-warehouse" name="warehouse" required value={warehouse} onChange={event => { setWarehouse(event.target.value); setQuantityError(""); }}>
              <option value="">Selecciona un almac&eacute;n</option>
              <option value="Los Angeles">Los &Aacute;ngeles</option>
              <option value="Zaragoza">Zaragoza</option>
            </select>

            <label htmlFor="outbound-quantity">Cantidad (unidades)</label>
            <input id="outbound-quantity" name="quantity" type="number" min="1" step="1" max={currentProduct?.current_stock ?? 0} required disabled={!currentProduct || stockLoading} value={quantity} aria-invalid={exceedsStock || Boolean(quantityError)} aria-describedby="outbound-stock outbound-quantity-warning outbound-quantity-error" onChange={event => { setQuantity(event.target.value); setQuantityError(""); }} />
            <div id="outbound-quantity-warning">
              {exceedsStock && <p role="alert" className="inventory-stock-low">La cantidad supera el stock global disponible. Reduce la cantidad antes de registrar la salida.</p>}
            </div>
            <div id="outbound-quantity-error">
              {quantityError && <p role="alert" className="inventory-stock-empty">{quantityError}</p>}
            </div>

            <button type="submit" disabled={!currentProduct || stockLoading || !validQuantity || exceedsStock || !warehouse}>
              {saving ? "Registrando salida..." : "Registrar salida"}
            </button>
          </fieldset>
        </form>
      </section>
    </main>
  );
}