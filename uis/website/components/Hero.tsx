export function Hero() {
  return (
    <section id="inicio" className="section-shell py-16 md:py-24">
      <div className="fade-up grid gap-8 md:grid-cols-[1.2fr_0.8fr] md:items-center">
        <div>
          <p className="mb-4 inline-flex rounded-full border border-[var(--brand)]/20 bg-white px-3 py-1 text-xs font-semibold tracking-[0.08em] text-[var(--brand-strong)] uppercase">
            Operador logistico binacional
          </p>
          <h1
            className="max-w-[14ch] text-4xl leading-tight font-semibold md:text-6xl"
            style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}
          >
            Logistica que escala con tu e-commerce
          </h1>
          <p className="mt-5 max-w-xl text-lg text-[var(--muted)]">
            Gestionamos inventario, fulfillment y entregas desde Los Angeles y Zaragoza para marcas que necesitan rapidez operativa en EE. UU. y Espana.
          </p>
          <a
            href="#contacto"
            className="mt-8 inline-flex rounded-full bg-[var(--accent)] px-6 py-3 text-sm font-semibold text-white transition hover:brightness-95"
          >
            Hablar con TrackFlow
          </a>
        </div>
        <div className="fade-up delay-1 card-glow rounded-3xl border border-black/5 bg-[var(--surface)] p-6 shadow-[0_20px_50px_rgba(21,34,42,0.08)]">
          <p className="text-sm font-semibold text-[var(--brand-strong)]">KPIs operativos en tiempo real</p>
          <ul className="mt-4 space-y-4 text-sm text-slate-700">
            <li className="rounded-2xl bg-[var(--surface-soft)] p-4">
              <strong className="block text-xl text-slate-900">+98.2%</strong>
              Precision media de inventario en ambos hubs.
            </li>
            <li className="rounded-2xl bg-[var(--surface-soft)] p-4">
              <strong className="block text-xl text-slate-900">24h</strong>
              Promesa estandar para despacho en pedidos aprobados.
            </li>
            <li className="rounded-2xl bg-[var(--surface-soft)] p-4">
              <strong className="block text-xl text-slate-900">16 carriers</strong>
              Integrados para optimizar costo y SLA por destino.
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}
