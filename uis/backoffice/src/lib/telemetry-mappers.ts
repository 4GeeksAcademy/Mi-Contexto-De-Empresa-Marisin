import type { SKUProduct } from "./inventory";

export function toWarehouse(value: string): "los_angeles" | "zaragoza" | null {
  const normalized = value.trim().toLowerCase();
  if (normalized === "los angeles" || normalized === "los_angeles") {
    return "los_angeles";
  }
  if (normalized === "zaragoza") return "zaragoza";
  return null;
}

export function toCountry(value: string): "US" | "ES" | null {
  const warehouse = toWarehouse(value);
  if (warehouse === "los_angeles") return "US";
  if (warehouse === "zaragoza") return "ES";
  return null;
}

export function toProductCategory(
  category: string,
  sku: string,
): "fashion" | "electronics" | "cosmetics" | null {
  if (sku.toUpperCase().startsWith("LOAD-")) return null;
  switch (category.trim().toLowerCase()) {
    case "apparel":
    case "accessories":
      return "fashion";
    case "electronics":
      return "electronics";
    case "beauty":
      return "cosmetics";
    default:
      return null;
  }
}

export function toClientId(value: string): string | null {
  const slug = value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug || null;
}

export function toExitType(
  value: string,
): "b2c_order" | "b2b_transfer" | "return_damaged" | null {
  switch (value.trim().toLowerCase()) {
    case "b2c order":
    case "b2c_order":
      return "b2c_order";
    case "b2b transfer":
    case "b2b_transfer":
      return "b2b_transfer";
    case "return / damaged":
    case "return_damaged":
      return "return_damaged";
    default:
      return null;
  }
}

export function toRouteTemplate(path: string): string {
  const pathOnly = path.split(/[?#]/, 1)[0];
  if (!pathOnly) return "/";
  const absolutePath = pathOnly.startsWith("/") ? pathOnly : `/${pathOnly}`;
  const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  return absolutePath
    .split("/")
    .map((segment) => (/^\d+$/.test(segment) || uuid.test(segment) ? "[id]" : segment))
    .join("/");
}

export function sanitizeErrorMessage(value: string): string {
  return value
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[redacted]")
    .replace(/\bBearer\s+\S+/gi, "Bearer [redacted]")
    .replace(/\beyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[redacted]")
    .replace(/\d{6,}/g, "[redacted]")
    .slice(0, 200);
}

export function toStackFrames(stack: string | null | undefined): string[] {
  if (!stack) return [];
  const frames: string[] = [];

  for (const line of stack.split("\n")) {
    const match = line.trim().match(/((?:https?:\/\/|webpack-internal:\/\/|file:\/\/)?[^()\s]+):(\d+)(?::\d+)?\)?$/);
    if (!match) continue;

    let filePath = match[1].split(/[?#]/, 1)[0];
    filePath = filePath.replace(/^[a-z]+:\/\/[^/]*/i, "");
    const sourceIndex = filePath.lastIndexOf("/src/");
    if (sourceIndex >= 0) {
      filePath = filePath.slice(sourceIndex + 5);
    } else {
      filePath = filePath.split("/").filter(Boolean).slice(-2).join("/");
    }

    const frame = `${filePath}:${Number(match[2])}`;
    if (/^[A-Za-z0-9_.\[\]/-]+:[1-9][0-9]*$/.test(frame) && !frame.startsWith("//")) {
      frames.push(frame);
      if (frames.length === 10) break;
    }
  }

  return frames;
}

export async function errorFingerprint(
  errorName: string,
  stackFrames: string[],
): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("Web Crypto SHA-256 is unavailable.");
  }
  const input = `${sanitizeErrorMessage(errorName)}\n${stackFrames[0] ?? ""}`;
  const digest = await globalThis.crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(input),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("").slice(0, 16);
}

export interface InventoryProperties {
  warehouse: "los_angeles" | "zaragoza";
  client_id: string;
  product_id: string;
  product_category: "fashion" | "electronics" | "cosmetics";
  quantity: number;
  country: "US" | "ES";
}

export function inventoryProperties(
  product: Pick<SKUProduct, "sku" | "client_name" | "category">,
  warehouse: string,
  quantity: number,
): InventoryProperties | null {
  const normalizedWarehouse = toWarehouse(warehouse);
  const country = toCountry(warehouse);
  const clientId = toClientId(product.client_name);
  const productId = product.sku.trim();
  const productCategory = toProductCategory(product.category, product.sku);

  if (
    !normalizedWarehouse ||
    !country ||
    !clientId ||
    !productId ||
    !productCategory ||
    !Number.isSafeInteger(quantity)
  ) {
    return null;
  }

  return {
    warehouse: normalizedWarehouse,
    client_id: clientId,
    product_id: productId,
    product_category: productCategory,
    quantity,
    country,
  };
}
