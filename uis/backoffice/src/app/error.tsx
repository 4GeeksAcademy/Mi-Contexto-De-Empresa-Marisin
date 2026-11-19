"use client";

import { useEffect } from "react";
import { captureFrontendError } from "@/components/TelemetryProvider";

export default function BackofficeError({
  error,
  reset,
}: {
  error: Error;
  reset: () => void;
}) {
  useEffect(() => {
    void captureFrontendError(error, "error_boundary");
  }, [error]);

  return (
    <main className="max-w-2xl mx-auto p-6 space-y-4">
      <p role="alert">No se pudo mostrar esta p&aacute;gina.</p>
      <button type="button" className="underline" onClick={reset}>
        Reintentar
      </button>
    </main>
  );
}
