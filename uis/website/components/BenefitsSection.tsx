const benefits = [
  "Operacion binacional integrada entre EE. UU. y Espana",
  "+130 profesionales especializados en operaciones omnicanal",
  "Tecnologia propia para monitoreo, SLA y analitica de fulfillment",
  "Especializacion e-commerce con enfoque en crecimiento rentable",
];

export function BenefitsSection() {
  return (
    <section className="section-shell py-16 md:py-20">
      <div className="mb-8">
        <h2 className="text-3xl font-semibold md:text-4xl" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>
          Por que TrackFlow
        </h2>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {benefits.map((benefit, index) => (
          <article
            key={benefit}
            className={`fade-up delay-${Math.min(index + 1, 3)} rounded-2xl border border-black/5 bg-white p-5 shadow-[0_8px_20px_rgba(21,34,42,0.05)]`}
          >
            <p className="text-sm text-slate-700">{benefit}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
