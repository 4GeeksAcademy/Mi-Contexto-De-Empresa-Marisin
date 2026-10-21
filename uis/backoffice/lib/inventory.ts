import { getAccessToken } from "../../application/lib/auth";

export interface ProductCreate {
  sku: string;
  name: string;
}

export interface Product extends ProductCreate {
  id: number;
  current_stock: number;
}

export interface InventoryOrderCreate {
  product_id: number;
  warehouse: string;
  quantity: number;
}

export interface InventoryOrderReceipt extends InventoryOrderCreate {
  id: number;
  created_at: string;
  user_uuid: string;
}

export interface InventoryOrder {
  id: number;
  order_type: "inbound" | "outbound";
  product: Pick<Product, "id" | "sku" | "name">;
  warehouse: string;
  quantity: number;
  created_at: string;
  user_uuid: string;
  user: {
    user_uuid: string;
    email: string | null;
    name: string | null;
  } | null;
}

export class InventoryApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: unknown = null,
  ) {
    super(message);
    this.name = "InventoryApiError";
  }
}

function errorMessage(body: unknown): string | undefined {
  if (typeof body === "string") return body.trim() || undefined;
  if (Array.isArray(body)) {
    return body.map(errorMessage).filter(Boolean).join("; ") || undefined;
  }
  if (body && typeof body === "object") {
    const fields = body as Record<string, unknown>;
    return (
      errorMessage(fields.detail) ??
      errorMessage(fields.message) ??
      errorMessage(fields.msg) ??
      JSON.stringify(body)
    );
  }
  return undefined;
}

async function inventoryRequest<T>(
  path: string,
  payload?: ProductCreate | InventoryOrderCreate,
  namespace: "/inventory" | "/auth" = "/inventory",
): Promise<T> {
  const token = getAccessToken();
  if (!token?.trim()) {
    throw new InventoryApiError("Debes iniciar sesi\u00f3n para acceder al inventario.", 401);
  }

  const baseUrl = process.env.NEXT_PUBLIC_INVENTORY_API_URL?.trim().replace(/\/+$/, "");
  if (!baseUrl) {
    throw new InventoryApiError("Falta configurar NEXT_PUBLIC_INVENTORY_API_URL.", 0);
  }

  const headers = new Headers({ Authorization: `Bearer ${token}` });
  if (payload !== undefined) headers.set("Content-Type", "application/json");

  const response = await fetch(`${baseUrl}${namespace}${path}`, {
    method: payload === undefined ? "GET" : "POST",
    headers,
    cache: "no-store",
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const text = await response.text();
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    if (response.ok) {
      throw new InventoryApiError("La API de inventario devolvi\u00f3 una respuesta JSON no v\u00e1lida.", response.status, text);
    }
    body = text;
  }

  if (!response.ok) {
    throw new InventoryApiError(
      errorMessage(body) ?? `Error de inventario (HTTP ${response.status}).`,
      response.status,
      body,
    );
  }
  return body as T;
}

export const inventoryApi = {
  verifySession: (): Promise<void> => inventoryRequest("/me", undefined, "/auth"),
  listProducts: (): Promise<Product[]> => inventoryRequest("/products"),
  getProduct: (productId: number): Promise<Product> =>
    inventoryRequest(`/products/${productId}`),
  createProduct: (payload: ProductCreate): Promise<Product> =>
    inventoryRequest("/products", payload),
  listOrders: (): Promise<InventoryOrder[]> => inventoryRequest("/orders"),
  createInboundOrder: (payload: InventoryOrderCreate): Promise<InventoryOrderReceipt> =>
    inventoryRequest("/orders/inbound", payload),
  createOutboundOrder: (payload: InventoryOrderCreate): Promise<InventoryOrderReceipt> =>
    inventoryRequest("/orders/outbound", payload),
};