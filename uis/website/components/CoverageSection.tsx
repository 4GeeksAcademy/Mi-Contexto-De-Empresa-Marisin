const hubs = [
  {
    city: "Los Angeles, EE. UU.",
    description: "Hub estrategico para costa oeste, importaciones y distribucion nacional.",
    carriers: ["UPS", "FedEx", "USPS", "OnTrac", "DHL eCommerce"],
  },
  {
    city: "Zaragoza, Espana",
    description: "Nodo para Iberia y Europa continental con control aduanero y cross-border.",
    carriers: ["Correos Express", "SEUR", "GLS", "MRW", "DHL Parcel"],
  },
];

export function CoverageSection() {
  return (
    <section id="cobertura" className="section-shell py-16 md:py-20">
      <div className="mb-8">
        <h2 className="text-3xl font-semibold md:text-4xl" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>
          Cobertura operativa
        </h2>
      </div>
      <div className="grid gap-6 md:grid-cols-2">
        {hubs.map((hub, index) => (
          <article
            key={hub.city}
            className={`fade-up delay-${Math.min(index + 1, 2)} rounded-3xl border border-black/5 bg-white p-7 shadow-[0_10px_24px_rgba(21,34,42,0.06)]`}
          >
            <h3 className="text-2xl font-semibold text-slate-900">{hub.city}</h3>
            <p className="mt-3 text-[var(--muted)]">{hub.description}</p>
            <p className="mt-5 text-sm font-semibold tracking-wide text-[var(--brand-strong)] uppercase">Carriers</p>
            <ul className="mt-3 flex flex-wrap gap-2">
              {hub.carriers.map((carrier) => (
                <li key={carrier} className="rounded-full bg-[var(--surface-soft)] px-3 py-1 text-sm text-slate-700">
                  {carrier}
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}
