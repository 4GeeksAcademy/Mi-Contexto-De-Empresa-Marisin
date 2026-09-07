import Link from "next/link";

export default function HomePage() {
  return (
    <main>
      <h1>TrackFlow</h1>
      <p>Gestiona tu directorio de proveedores.</p>
      <p>
        <Link href="/login">Iniciar sesión</Link>
        {" o "}
        <Link href="/register">crear una cuenta</Link>
      </p>
    </main>
  );
}