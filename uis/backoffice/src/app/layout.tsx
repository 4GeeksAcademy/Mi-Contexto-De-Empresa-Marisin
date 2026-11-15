import type { ReactNode } from "react";
import type { Metadata } from "next";
import "./globals.css";
import BackofficeNav from "../components/BackofficeNav";

export const metadata: Metadata = {
  title: "TrackFlow Backoffice | Operaciones e Inventario",
  description:
    "Panel interno de TrackFlow para gestionar inventario y órdenes de entrada y salida.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>
        <BackofficeNav />
        {children}
      </body>
    </html>
  );
}