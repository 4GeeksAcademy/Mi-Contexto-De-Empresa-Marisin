const services = [
  {
    title: "Gestion de Almacenes",
    description:
      "Control de inventario, picking, packing y trazabilidad por SKU con visibilidad operativa para tu equipo.",
  },
  {
    title: "Entregas de Ultima Milla",
    description:
      "Asignacion inteligente de transportistas para acelerar entregas y mejorar la experiencia post-compra.",
  },
  {
    title: "Logistica Inversa",
    description:
      "Procesamiento estructurado de devoluciones con inspeccion, reacondicionamiento y reincorporacion al stock.",
  },
];

export function ServicesSection() {
  return (
    <section id="servicios" className="section-shell py-16 md:py-20">
      <div className="mb-8">
        <h2 className="text-3xl font-semibold md:text-4xl" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>
          Servicios clave
        </h2>
      </div>
      <div className="grid gap-5 md:grid-cols-3">
        {services.map((service, index) => (
          <article
            key={service.title}
            className={`fade-up delay-${Math.min(index + 1, 3)} rounded-3xl border border-black/5 bg-white p-6 shadow-[0_10px_24px_rgba(21,34,42,0.06)]`}
          >
            <h3 className="text-xl font-semibold text-slate-900">{service.title}</h3>
            <p className="mt-3 text-[var(--muted)]">{service.description}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
