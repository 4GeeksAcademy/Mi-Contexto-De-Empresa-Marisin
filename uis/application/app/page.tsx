import Link from "next/link";

import { DashboardShell } from "@/components/DashboardShell";
import { OperationsPanel } from "@/components/OperationsPanel";
import { TalentPanel } from "@/components/TalentPanel";

export default function Home() {
  return (
    <>
      <nav className="flex justify-end gap-4 px-6 pt-4 text-sm">
        <Link href="/login">Iniciar sesión</Link>
        <Link href="/register">Crear una cuenta</Link>
      </nav>
      <DashboardShell>
        <div className="grid gap-6 xl:grid-cols-2">
          <OperationsPanel />
          <TalentPanel />
        </div>
      </DashboardShell>
    </>
  );
}
