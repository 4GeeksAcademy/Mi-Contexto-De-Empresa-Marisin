"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  clearSessionAndRedirect,
  protectedFetch,
  UnauthorizedError,
} from "../../api";

type Profile = {
  name: string | null;
  phone: string | null;
  address: string | null;
};

type CurrentUser = {
  email: string;
  profile: Profile | null;
};

type ProfileForm = {
  name: string;
  phone: string;
  address: string;
};

type ApiError = {
  detail?: string;
};

export default function ProfilePage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [form, setForm] = useState<ProfileForm>({
    name: "",
    phone: "",
    address: "",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let isCurrent = true;

    async function loadProfile() {
      const token = localStorage.getItem("token");
      if (!token) {
        router.replace("/login");
        return;
      }

      try {
        const response = await protectedFetch("/auth/me");

        if (!response.ok) {
          throw new Error("No se pudo cargar la información de tu cuenta.");
        }

        const data = (await response.json()) as CurrentUser;
        if (!isCurrent) {
          return;
        }

        setEmail(data.email);
        setForm({
          name: data.profile?.name ?? "",
          phone: data.profile?.phone ?? "",
          address: data.profile?.address ?? "",
        });
      } catch (requestError) {
        if (requestError instanceof UnauthorizedError) {
          return;
        }

        if (isCurrent) {
          setError(
            requestError instanceof Error
              ? requestError.message
              : "No se pudo cargar tu perfil.",
          );
        }
      } finally {
        if (isCurrent) {
          setLoading(false);
        }
      }
    }

    void loadProfile();

    return () => {
      isCurrent = false;
    };
  }, [router]);

  function updateField(field: keyof ProfileForm, value: string) {
    setForm((currentForm) => ({ ...currentForm, [field]: value }));
  }

  async function getErrorMessage(response: Response, fallback: string) {
    const data = (await response.json().catch(() => null)) as ApiError | null;
    return data?.detail ?? fallback;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setMessage("");
    setSaving(true);

    try {
      const response = await protectedFetch("/profiles/me", {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          name: form.name || null,
          phone: form.phone || null,
          address: form.address || null,
        }),
      });

      if (!response.ok) {
        throw new Error(
          await getErrorMessage(response, "No se pudo actualizar el perfil."),
        );
      }

      const updatedProfile = (await response.json()) as Profile;
      setForm({
        name: updatedProfile.name ?? "",
        phone: updatedProfile.phone ?? "",
        address: updatedProfile.address ?? "",
      });
      setMessage("Perfil actualizado correctamente.");
    } catch (requestError) {
      if (requestError instanceof UnauthorizedError) {
        return;
      }

      setError(
        requestError instanceof Error
          ? requestError.message
          : "No se pudo conectar con el servidor.",
      );
    } finally {
      setSaving(false);
    }
  }

  function handleLogout() {
    clearSessionAndRedirect();
  }

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-950 px-6">
        <p className="text-sm text-slate-400">Cargando tu perfil...</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-12 text-white">
      <div className="mx-auto max-w-2xl">
        <header className="mb-8 flex items-start justify-between gap-4">
          <div>
            <p className="mb-3 text-sm font-semibold uppercase tracking-[0.2em] text-cyan-400">
              TrackFlow
            </p>
            <h1 className="text-3xl font-bold tracking-tight">Mi cuenta</h1>
            <p className="mt-2 text-sm text-slate-400">
              Administra tus datos personales.
            </p>
          </div>
          <button
            className="rounded-lg border border-slate-700 px-4 py-2 text-sm font-medium text-slate-200 transition hover:border-red-400 hover:text-red-300 focus:outline-none focus:ring-2 focus:ring-red-400/40"
            onClick={handleLogout}
            type="button"
          >
            Cerrar sesión
          </button>
        </header>

        <section className="rounded-2xl border border-slate-800 bg-slate-900 p-8 shadow-2xl shadow-slate-950/50">
          <form className="space-y-6" onSubmit={handleSubmit}>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="email">
                Email
              </label>
              <input
                className="w-full cursor-not-allowed rounded-lg border border-slate-700 bg-slate-950/60 px-4 py-3 text-slate-400 outline-none"
                id="email"
                readOnly
                type="email"
                value={email}
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="name">
                Nombre
              </label>
              <input
                autoComplete="name"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
                id="name"
                onChange={(event) => updateField("name", event.target.value)}
                placeholder="Tu nombre"
                type="text"
                value={form.name}
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="phone">
                Teléfono
              </label>
              <input
                autoComplete="tel"
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
                id="phone"
                onChange={(event) => updateField("phone", event.target.value)}
                placeholder="+34 600 000 000"
                type="tel"
                value={form.phone}
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-slate-200" htmlFor="address">
                Dirección
              </label>
              <textarea
                autoComplete="street-address"
                className="min-h-28 w-full resize-y rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none transition placeholder:text-slate-600 focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20"
                id="address"
                onChange={(event) => updateField("address", event.target.value)}
                placeholder="Calle, ciudad"
                value={form.address}
              />
            </div>

            {error && (
              <p
                aria-live="polite"
                className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200"
                role="alert"
              >
                {error}
              </p>
            )}

            {message && (
              <p
                aria-live="polite"
                className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200"
                role="status"
              >
                {message}
              </p>
            )}

            <button
              className="flex w-full items-center justify-center rounded-lg bg-cyan-400 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-300 focus:outline-none focus:ring-2 focus:ring-cyan-300 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:cursor-not-allowed disabled:opacity-60"
              disabled={saving}
              type="submit"
            >
              {saving ? "Guardando cambios..." : "Guardar cambios"}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
