"use client";

import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { track } from "@/lib/telemetry";
import {
  errorFingerprint,
  toRouteTemplate,
  toStackFrames,
} from "@/lib/telemetry-mappers";

const errorSources = {
  window_error: "Error de JavaScript",
  unhandled_rejection: "Promesa rechazada sin manejar",
  error_boundary: "Error de renderizado",
};

export async function captureFrontendError(
  reason: unknown,
  source: keyof typeof errorSources,
) {
  try {
    const route = toRouteTemplate(window.location.pathname);
    const error = reason instanceof Error ? reason : undefined;
    const frames = toStackFrames(error?.stack);
    const fingerprint = await errorFingerprint(error?.name || "Error", frames);

    track("frontend_error_captured", {
      route,
      // Raw exceptions can contain form values that redaction cannot reliably identify.
      message: errorSources[source],
      stack_frames: frames,
      error_source: source,
      error_fingerprint: fingerprint,
    });
  } catch {
    // Error reporting must not generate another uncaught error.
  }
}

export default function TelemetryProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  useEffect(() => {
    if (pathname) track("page_viewed", { route: toRouteTemplate(pathname) });
  }, [pathname]);

  useEffect(() => {
    function handleError(event: ErrorEvent) {
      void captureFrontendError(event.error, "window_error");
    }

    function handleRejection(event: PromiseRejectionEvent) {
      void captureFrontendError(event.reason, "unhandled_rejection");
    }

    window.addEventListener("error", handleError);
    window.addEventListener("unhandledrejection", handleRejection);
    return () => {
      window.removeEventListener("error", handleError);
      window.removeEventListener("unhandledrejection", handleRejection);
    };
  }, []);

  return children;
}
