import { Suspense } from "react";
import TalentHomeClient from "@/components/TalentHomeClient";

function PageFallback() {
  return (
    <div className="min-h-screen bg-[linear-gradient(160deg,#f8fafc_0%,#e2e8f0_42%,#f1f5f9_100%)] px-4 py-8 text-slate-900 sm:px-6 lg:px-10">
      <main className="mx-auto w-full max-w-6xl">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className="mb-5 flex items-center gap-3 text-slate-700">
            <span className="h-5 w-5 animate-spin rounded-full border-2 border-cyan-700 border-t-transparent" />
            <p className="font-medium">Cargando panel de talento...</p>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function HomePage() {
  return (
    <Suspense fallback={<PageFallback />}>
      <TalentHomeClient />
    </Suspense>
  );
}
