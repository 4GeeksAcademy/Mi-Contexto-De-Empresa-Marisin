import type { Metadata } from "next";
import { Manrope, Space_Grotesk } from "next/font/google";
import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-manrope",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://trackflow-logistics.com"),
  title: "TrackFlow | Logistica para e-commerce entre EE. UU. y Espana",
  description:
    "TrackFlow opera desde Los Angeles y Zaragoza para escalar operaciones de e-commerce con almacenaje, ultima milla y logistica inversa.",
  keywords: [
    "operador logistico",
    "logistica e-commerce",
    "last mile",
    "3PL Los Angeles",
    "3PL Zaragoza",
    "logistica inversa",
  ],
  openGraph: {
    title: "TrackFlow | Logistica que escala con tu e-commerce",
    description:
      "Operacion binacional con tecnologia propia para marcas que venden en EE. UU. y Espana.",
    type: "website",
    url: "https://trackflow-logistics.com",
    siteName: "TrackFlow",
    locale: "es_ES",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body
        className={`${manrope.variable} ${spaceGrotesk.variable} antialiased`}
        style={{ fontFamily: "var(--font-manrope), sans-serif" }}
      >
        {children}
      </body>
    </html>
  );
}
