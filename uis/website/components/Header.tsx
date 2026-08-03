const navigation = [
  { label: "Inicio", href: "#inicio" },
  { label: "Servicios", href: "#servicios" },
  { label: "Cobertura", href: "#cobertura" },
  { label: "Contacto", href: "#contacto" },
];

export function Header() {
  return (
    <header className="sticky top-0 z-30 border-b border-black/5 bg-[rgba(255,255,255,0.82)] backdrop-blur-md">
      <div className="section-shell flex items-center justify-between py-4">
        <div className="text-lg font-semibold tracking-tight" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>
          TrackFlow
        </div>
        <nav aria-label="Navegacion principal" className="hidden gap-6 text-sm md:flex">
          {navigation.map((item) => (
            <a key={item.href} href={item.href} className="text-slate-700 transition hover:text-[var(--brand-strong)]">
              {item.label}
            </a>
          ))}
        </nav>
        <a
          href="#contacto"
          className="rounded-full bg-[var(--brand)] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[var(--brand-strong)]"
        >
          Solicitar demo
        </a>
      </div>
    </header>
  );
}
