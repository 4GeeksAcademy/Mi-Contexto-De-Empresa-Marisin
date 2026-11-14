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

// --- Funciones de Servicio de Inventario ---

export async function getProducts(): Promise<SKUProduct[]> {
  return fetchWithAuth("/inventory/products");
}

export async function getProductById(id: number): Promise<SKUProduct> {
  return fetchWithAuth(`/inventory/products/${id}`);
}

export async function createInboundOrder(payload: InboundOrderPayload) {
  return fetchWithAuth("/inventory/orders/inbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createOutboundOrder(payload: OutboundOrderPayload) {
  return fetchWithAuth("/inventory/orders/outbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getOrders(): Promise<InventoryOrder[]> {
  return fetchWithAuth("/inventory/orders");
}
