import type { ReactNode } from "react";
import InventoryLayout from "../inventory/layout";

// Misma comprobación de sesión que inventario, reporting y el asistente (/auth/me).
export default function RfpLayout({ children }: { children: ReactNode }) {
  return <InventoryLayout>{children}</InventoryLayout>;
}
