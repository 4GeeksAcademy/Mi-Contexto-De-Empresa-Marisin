const API_URL = process.env.NEXT_PUBLIC_INVENTORY_API_URL || "http://localhost:8000";

// Auxiliar para obtener el token del almacenamiento local
function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("access_token") || localStorage.getItem("token");
}

// Auxiliar para peticiones HTTP centralizadas
async function fetchWithAuth(endpoint: string, options: RequestInit = {}) {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorMessage = `Error ${response.status}: ${response.statusText}`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        errorMessage = typeof errorData.detail === "string" 
          ? errorData.detail 
          : JSON.stringify(errorData.detail);
      }
    } catch {
      // Si el cuerpo no es JSON, mantenemos el mensaje de estado
    }
    throw new Error(errorMessage);
  }

  return response.json();
}

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
  product: SKUProduct;
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
