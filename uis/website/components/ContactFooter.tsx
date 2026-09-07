export function ContactFooter() {
  return (
    <>
      <section className="section-shell mt-16 rounded-3xl border border-black/5 bg-[var(--surface)] p-8 md:p-10">
        <h2 className="text-2xl font-semibold md:text-3xl" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>
          Equipo comercial
        </h2>
        <div className="mt-5 grid gap-6 md:grid-cols-2">
          <div>
            <p className="font-semibold text-slate-900">TrackFlow USA</p>
            <p className="mt-1 text-slate-700">Los Angeles Fulfillment Hub</p>
            <p className="text-slate-700">sales.us@trackflow-logistics.com</p>
            <p className="text-slate-700">+1 323 555 0188</p>
          </div>
          <div>
            <p className="font-semibold text-slate-900">TrackFlow Espana</p>
            <p className="mt-1 text-slate-700">Zaragoza Operations Center</p>
            <p className="text-slate-700">sales.es@trackflow-logistics.com</p>
            <p className="text-slate-700">+34 976 555 214</p>
          </div>
        </div>
        <div className="mt-6 flex flex-wrap gap-4 text-sm text-[var(--brand-strong)]">
          <a href="https://www.linkedin.com" target="_blank" rel="noreferrer" className="hover:underline">
            LinkedIn
          </a>
          <a href="https://x.com" target="_blank" rel="noreferrer" className="hover:underline">
            X
          </a>
          <a href="https://www.instagram.com" target="_blank" rel="noreferrer" className="hover:underline">
            Instagram
          </a>
        </div>
      </section>
      <footer className="section-shell py-10 text-sm text-[var(--muted)]">
        © {new Date().getFullYear()} TrackFlow. Todos los derechos reservados.
      </footer>
    </>
  );
}
