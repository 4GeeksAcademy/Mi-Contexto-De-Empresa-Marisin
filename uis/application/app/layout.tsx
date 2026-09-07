import type { Metadata } from "next";
import { IBM_Plex_Sans, Space_Grotesk } from "next/font/google";
import "./globals.css";

const ibmPlex = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-ibm-plex",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
});

export const metadata: Metadata = {
  title: "TrackFlow Backoffice",
  description: "Panel interno para seguimiento de talento y operaciones logisticas de TrackFlow.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body
        className={`${ibmPlex.variable} ${spaceGrotesk.variable} antialiased`}
        style={{ fontFamily: "var(--font-ibm-plex), sans-serif" }}
      >
        {children}
      </body>
    </html>
  );
}
