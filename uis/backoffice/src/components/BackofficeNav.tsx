"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

const LINKS = [
  { href: "/inventory/products", label: "Productos" },
  { href: "/inventory/orders", label: "Historial" },
  { href: "/inventory/orders/inbound", label: "Registrar entrada" },
  { href: "/inventory/orders/outbound", label: "Registrar salida" },
];

export default function BackofficeNav() {
  const pathname = usePathname();
  const router = useRouter();

  // En el login y en la portada (que redirige al login) no se muestra el menú
  if (pathname === "/login" || pathname === "/") return null;

  function handleLogout() {
    localStorage.removeItem("access_token");
    localStorage.removeItem("token");
    router.push("/login");
  }

  return (
    <header className="border-b border-gray-200 bg-white">
      <nav
        aria-label="Navegación principal"
        className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-6 py-3"
      >
        <Link href="/inventory/products" className="text-base font-semibold text-gray-900">
          TrackFlow Backoffice
        </Link>

        <ul className="flex flex-wrap items-center gap-1 text-sm">
          {LINKS.map((link) => {
            const isActive = pathname === link.href;
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={isActive ? "page" : undefined}
                  className={`rounded-md px-3 py-2 transition-colors ${
                    isActive
                      ? "bg-gray-900 text-white"
                      : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
                  }`}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
          <li>
            <button
              type="button"
              onClick={handleLogout}
              className="ml-2 rounded-md px-3 py-2 text-gray-600 transition-colors hover:bg-red-50 hover:text-red-700"
            >
              Cerrar sesión
            </button>
          </li>
        </ul>
      </nav>
    </header>
  );
}
