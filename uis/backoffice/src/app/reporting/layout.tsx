import type { ReactNode } from "react";
import InventoryLayout from "../inventory/layout";

// Misma comprobación de sesión que las páginas de inventario (/auth/me).
export default function ReportingLayout({ children }: { children: ReactNode }) {
  return <InventoryLayout>{children}</InventoryLayout>;
}
