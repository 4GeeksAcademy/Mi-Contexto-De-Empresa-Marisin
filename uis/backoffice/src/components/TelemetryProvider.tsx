"use client";

import { usePathname } from "next/navigation";
import { useReportWebVitals } from "next/web-vitals";
import { useEffect, useRef, type FormEvent, type ReactNode } from "react";
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

function isOrderField(name: string) {
  return name === "sku" || name === "warehouse" || name === "quantity"
    || name === "exit_type" || name === "tracking_number";
}

export function useOrderFormTelemetry(orderKind: "inbound" | "outbound") {
  const form = useRef<HTMLFormElement | null>(null);
  const interaction = useRef<{ startedAt: number; lastField: string; abandoned: boolean } | null>(null);

  function touchField(event: FormEvent<HTMLFormElement>) {
    const field = event.target;
    if (!(field instanceof HTMLInputElement || field instanceof HTMLSelectElement)
        || !isOrderField(field.name)) return;
    if (interaction.current) {
      interaction.current.lastField = field.name;
      return;
    }
    form.current = event.currentTarget;
    interaction.current = { startedAt: performance.now(), lastField: field.name, abandoned: false };
    track("order_form_started", { order_kind: orderKind });
  }

  useEffect(() => {
    function abandon() {
      const current = interaction.current;
      if (!current || current.abandoned || !form.current) return;
      current.abandoned = true;
      const completed = Array.from(form.current.elements).filter((field) =>
        (field instanceof HTMLInputElement || field instanceof HTMLSelectElement)
        && isOrderField(field.name) && field.validity.valid && field.value.trim() !== "",
      ).length;
      track("order_form_abandoned", {
        order_kind: orderKind,
        last_field_touched: current.lastField,
        fields_completed: completed,
        time_in_form_ms: Math.round(performance.now() - current.startedAt),
      });
    }

    function onVisibilityChange() {
      if (document.visibilityState === "hidden") abandon();
    }
    // Capture before the telemetry service's visibility listener flushes the queue.
    document.addEventListener("visibilitychange", onVisibilityChange, true);
    return () => {
      document.removeEventListener("visibilitychange", onVisibilityChange, true);
      abandon();
    };
  }, [orderKind]);

  return { touchField, resetForm: () => { interaction.current = null; form.current = null; } };
}

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

const REPORTED_WEB_VITALS = new Set(["LCP", "INP", "CLS"]);
const reportedWebVitalIds = new Set<string>();

// Callback estable (fuera del componente): una observación final por métrica y carga de página.
function reportWebVital(metric: { id: string; name: string; value: number }) {
  try {
    if (!REPORTED_WEB_VITALS.has(metric.name) || reportedWebVitalIds.has(metric.id)) return;
    if (!Number.isFinite(metric.value) || metric.value < 0) return;
    reportedWebVitalIds.add(metric.id);
    track("web_vital_recorded", {
      route: toRouteTemplate(window.location.pathname),
      metric_name: metric.name,
      metric_value: metric.value,
    });
  } catch {
    // Las métricas de rendimiento nunca deben romper la aplicación.
  }
}

export default function TelemetryProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  useReportWebVitals(reportWebVital);

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
