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
