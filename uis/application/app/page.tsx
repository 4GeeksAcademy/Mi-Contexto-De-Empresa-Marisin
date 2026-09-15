<<<<<<< HEAD
import { DashboardShell } from "@/components/DashboardShell";
import { OperationsPanel } from "@/components/OperationsPanel";
import { TalentPanel } from "@/components/TalentPanel";

export default function Home() {
  return (
    <DashboardShell>
      <div className="grid gap-6 xl:grid-cols-2">
        <OperationsPanel />
        <TalentPanel />
      </div>
    </DashboardShell>
  );
}
=======
import Link from "next/link";

export default function HomePage() {
  return (
    <main>
      <h1>TrackFlow</h1>
      <p>Gestiona tu directorio de proveedores.</p>
      <p>
        <Link href="/login">Iniciar sesión</Link>
        {" o "}
        <Link href="/register">crear una cuenta</Link>
      </p>
    </main>
  );
}
>>>>>>> origin/feature/auth-frontend
