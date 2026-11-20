import type { ReactNode } from "react";
import InventoryLayout from "../inventory/layout";

// Misma comprobación de sesión que inventario y reporting (/auth/me).
export default function KnowledgeLayout({ children }: { children: ReactNode }) {
  return <InventoryLayout>{children}</InventoryLayout>;
}
