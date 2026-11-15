import type { ReactNode } from "react";
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "TrackFlow Backoffice | Operaciones e Inventario",
  description:
    "Panel interno de TrackFlow para gestionar inventario y órdenes de entrada y salida.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}