export const metadata = {
  title: "TrackFlow",
  description: "Gestión del directorio de proveedores",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
