"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";

const CONTACT_SECTION_ID = "contacto";

function LeadFormPlaceholder() {
  return <div aria-hidden="true" className="min-h-[75rem] md:min-h-[49rem]" />;
}

const LazyLeadFormContent = dynamic(
  () => import("./LeadForm").then((module) => module.LeadForm),
  {
    ssr: false,
    loading: () => <LeadFormPlaceholder />,
  },
);

export function LazyLeadForm() {
  const sectionRef = useRef<HTMLElement>(null);
  const [shouldLoad, setShouldLoad] = useState(false);

  useEffect(() => {
    const loadForContactAnchor = () => {
      if (window.location.hash === `#${CONTACT_SECTION_ID}`) {
        setShouldLoad(true);
      }
    };

    loadForContactAnchor();
    window.addEventListener("hashchange", loadForContactAnchor);

    if (!("IntersectionObserver" in window)) {
      setShouldLoad(true);
      return () => window.removeEventListener("hashchange", loadForContactAnchor);
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShouldLoad(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" },
    );

    if (sectionRef.current) {
      observer.observe(sectionRef.current);
    }

    return () => {
      observer.disconnect();
      window.removeEventListener("hashchange", loadForContactAnchor);
    };
  }, []);

  return (
    <section
      ref={sectionRef}
      id={CONTACT_SECTION_ID}
      className="section-shell py-16 md:py-20"
    >
      <div className="mb-8 max-w-2xl">
        <h2
          className="text-3xl font-semibold md:text-4xl"
          style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}
        >
          Conversemos sobre tu operacion
        </h2>
        <p className="mt-3 text-[var(--muted)]">
          Completa el formulario para que el equipo comercial de TrackFlow te
          contacte con un plan de escalado operativo.
        </p>
      </div>
      {shouldLoad ? <LazyLeadFormContent /> : <LeadFormPlaceholder />}
    </section>
  );
}
