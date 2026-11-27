import { fetchWithAuth } from "./api";

// --- Interfaces de Datos de TrackFlow ---
export interface SKUProduct {
  id: number;
  sku: string;
  name: string;
  client_name: string;
  category: string;
  reference: string;
  current_stock: number;
}

export interface InboundOrderPayload {
  sku_id: number;
  warehouse: string;
  quantity: number;
}

export interface OutboundOrderPayload {
  sku_id: number;
  warehouse: string;
  quantity: number;
  exit_type: string;
  tracking_number?: string;
  /** Confirmación humana de un despacho de alto valor (la API responde 409 si falta). */
  confirm_high_value?: boolean;
}

export interface InventoryOrder {
  id: number;
  order_type: "inbound" | "outbound";
  product: Pick<SKUProduct, "sku" | "name">;
  warehouse: string;
  quantity: number;
  created_at: string;
  user_uuid: string;
}

export function computeStockIndex(orders: InventoryOrder[]) {
  const index = new Map<string, number>();
  for (const order of orders) {
    const key = `${order.product.sku}|${order.warehouse}`;
    const quantity = order.order_type === "inbound" ? order.quantity : -order.quantity;
    index.set(key, (index.get(key) ?? 0) + quantity);
  }
  return index;
}

// --- Funciones de Servicio de Inventario ---

export async function getProducts(): Promise<SKUProduct[]> {
  return fetchWithAuth("/inventory/products");
}

export async function getProductById(id: number): Promise<SKUProduct> {
  return fetchWithAuth(`/inventory/products/${id}`);
}

export async function createInboundOrder(payload: InboundOrderPayload): Promise<{ id: number }> {
  return fetchWithAuth("/inventory/orders/inbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createOutboundOrder(payload: OutboundOrderPayload): Promise<{ id: number }> {
  return fetchWithAuth("/inventory/orders/outbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getOrders(): Promise<InventoryOrder[]> {
  return fetchWithAuth("/inventory/orders");
}

// La API rechaza siempre este intento con 405 (D28): el stock solo cambia con órdenes.
export async function requestDirectStockEdit(
  productId: number,
  warehouse: string,
  quantity: number,
): Promise<unknown> {
  return fetchWithAuth(`/inventory/products/${productId}/stock`, {
    method: "PATCH",
    body: JSON.stringify({ warehouse, quantity }),
  });
}
