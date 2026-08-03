"use client";

import { useMemo, useState } from "react";

type LeadFormState = {
  companyName: string;
  contactPerson: string;
  corporateEmail: string;
  phone: string;
  website: string;
  operatingCountry: string;
  productType: string;
  monthlyVolume: string;
  serviceInterests: string[];
  current3pl: string;
  comments: string;
  privacyAccepted: boolean;
};

type LeadFormErrors = Partial<Record<keyof LeadFormState, string>>;

const serviceOptions = ["Gestion de Almacenes", "Ultima Milla", "Logistica Inversa"];
const freeEmailDomains = [
  "gmail.com",
  "hotmail.com",
  "outlook.com",
  "yahoo.com",
  "icloud.com",
  "live.com",
  "aol.com",
  "protonmail.com",
];
const commentsMaxLength = 500;

const initialState: LeadFormState = {
  companyName: "",
  contactPerson: "",
  corporateEmail: "",
  phone: "",
  website: "",
  operatingCountry: "",
  productType: "",
  monthlyVolume: "",
  serviceInterests: [],
  current3pl: "",
  comments: "",
  privacyAccepted: false,
};

export function LeadForm() {
  const [formData, setFormData] = useState<LeadFormState>(initialState);
  const [errors, setErrors] = useState<LeadFormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);

  const lowVolumeWarning = useMemo(() => Number(formData.monthlyVolume) < 100, [formData.monthlyVolume]);

  const updateField = <K extends keyof LeadFormState>(field: K, value: LeadFormState[K]) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setErrors((prev) => ({ ...prev, [field]: undefined }));
  };

  const validate = () => {
    const nextErrors: LeadFormErrors = {};

    if (formData.companyName.trim().length < 3) {
      nextErrors.companyName = "El nombre de empresa debe tener al menos 3 caracteres.";
    }

    if (formData.contactPerson.trim().length < 3) {
      nextErrors.contactPerson = "La persona de contacto debe tener al menos 3 caracteres.";
    }

    const email = formData.corporateEmail.trim().toLowerCase();
    const emailParts = email.split("@");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      nextErrors.corporateEmail = "Ingresa un email valido con formato nombre@empresa.com.";
    } else if (emailParts.length === 2 && freeEmailDomains.includes(emailParts[1])) {
      nextErrors.corporateEmail = "Utiliza un email corporativo; no se aceptan dominios personales.";
    }

    if (!/^\+[1-9]\d{7,14}$/.test(formData.phone.trim())) {
      nextErrors.phone = "El telefono debe incluir codigo de pais en formato internacional (ej: +34976123456).";
    }

    try {
      const parsed = new URL(formData.website.trim());
      if (!(parsed.protocol === "https:" || parsed.protocol === "http:")) {
        nextErrors.website = "El sitio web debe iniciar con http:// o https://.";
      }
    } catch {
      nextErrors.website = "Ingresa una URL valida para el sitio web corporativo.";
    }

    if (!formData.operatingCountry) {
      nextErrors.operatingCountry = "Selecciona el pais de operacion principal.";
    }

    if (formData.productType.trim().length < 3) {
      nextErrors.productType = "Describe el tipo de producto con al menos 3 caracteres.";
    }

    if (!formData.monthlyVolume || Number(formData.monthlyVolume) <= 0) {
      nextErrors.monthlyVolume = "Indica un volumen mensual valido en numero de envios.";
    }

    if (formData.serviceInterests.length === 0) {
      nextErrors.serviceInterests = "Selecciona al menos un servicio de interes.";
    }

    if (formData.current3pl.trim().length < 2) {
      nextErrors.current3pl = "Indica tu 3PL actual o escribe 'Ninguno'.";
    }

    if (formData.comments.trim().length < 20) {
      nextErrors.comments = "Incluye al menos 20 caracteres para contexto operativo.";
    } else if (formData.comments.length > commentsMaxLength) {
      nextErrors.comments = `No excedas ${commentsMaxLength} caracteres en comentarios.`;
    }

    if (!formData.privacyAccepted) {
      nextErrors.privacyAccepted = "Debes aceptar la politica de privacidad para continuar.";
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!validate()) {
      return;
    }

    setIsSubmitting(true);
    await new Promise((resolve) => setTimeout(resolve, 1200));
    setIsSubmitting(false);
    setIsSubmitted(true);
  };

  return (
    <section id="contacto" className="section-shell py-16 md:py-20">
      <div className="mb-8 max-w-2xl">
        <h2 className="text-3xl font-semibold md:text-4xl" style={{ fontFamily: "var(--font-space-grotesk), sans-serif" }}>
          Conversemos sobre tu operacion
        </h2>
        <p className="mt-3 text-[var(--muted)]">
          Completa el formulario para que el equipo comercial de TrackFlow te contacte con un plan de escalado operativo.
        </p>
      </div>

      <form onSubmit={onSubmit} noValidate className="grid gap-5 rounded-3xl border border-black/5 bg-white p-6 md:grid-cols-2 md:p-8">
        <Field label="Nombre de empresa" error={errors.companyName}>
          <input
            value={formData.companyName}
            onChange={(event) => updateField("companyName", event.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
        </Field>

        <Field label="Persona de contacto" error={errors.contactPerson}>
          <input
            value={formData.contactPerson}
            onChange={(event) => updateField("contactPerson", event.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
        </Field>

        <Field label="Email corporativo" error={errors.corporateEmail}>
          <input
            type="email"
            value={formData.corporateEmail}
            onChange={(event) => updateField("corporateEmail", event.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
        </Field>

        <Field label="Telefono" error={errors.phone}>
          <input
            type="tel"
            value={formData.phone}
            onChange={(event) => updateField("phone", event.target.value)}
            placeholder="+34976123456"
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
        </Field>

        <Field label="Sitio web" error={errors.website}>
          <input
            type="url"
            value={formData.website}
            onChange={(event) => updateField("website", event.target.value)}
            placeholder="https://tuempresa.com"
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
        </Field>

        <Field label="Pais de operacion principal" error={errors.operatingCountry}>
          <select
            value={formData.operatingCountry}
            onChange={(event) => updateField("operatingCountry", event.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          >
            <option value="">Selecciona un pais</option>
            <option value="Estados Unidos">Estados Unidos</option>
            <option value="Espana">Espana</option>
            <option value="Mexico">Mexico</option>
            <option value="Otro">Otro</option>
          </select>
        </Field>

        <Field label="Tipo de producto" error={errors.productType}>
          <input
            value={formData.productType}
            onChange={(event) => updateField("productType", event.target.value)}
            placeholder="Cosmetica, moda, electronica..."
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
        </Field>

        <Field label="Volumen mensual (envios)" error={errors.monthlyVolume}>
          <input
            type="number"
            min={1}
            value={formData.monthlyVolume}
            onChange={(event) => updateField("monthlyVolume", event.target.value)}
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
        </Field>

        <div className="md:col-span-2">
          <p className="text-sm font-semibold text-slate-900">Servicios de interes</p>
          <div className="mt-2 flex flex-wrap gap-3">
            {serviceOptions.map((service) => {
              const checked = formData.serviceInterests.includes(service);
              return (
                <label key={service} className="flex items-center gap-2 rounded-full border border-slate-300 px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(event) => {
                      updateField(
                        "serviceInterests",
                        event.target.checked
                          ? [...formData.serviceInterests, service]
                          : formData.serviceInterests.filter((item) => item !== service),
                      );
                    }}
                  />
                  {service}
                </label>
              );
            })}
          </div>
          {errors.serviceInterests ? <p className="mt-1 text-sm text-red-600">{errors.serviceInterests}</p> : null}
        </div>

        <Field label="3PL actual" error={errors.current3pl}>
          <input
            value={formData.current3pl}
            onChange={(event) => updateField("current3pl", event.target.value)}
            placeholder="Nombre del operador o Ninguno"
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
        </Field>

        <div>
          <label className="mb-1 block text-sm font-semibold text-slate-900" htmlFor="comments">
            Comentarios
          </label>
          <textarea
            id="comments"
            value={formData.comments}
            onChange={(event) => updateField("comments", event.target.value)}
            maxLength={commentsMaxLength}
            rows={5}
            className="w-full rounded-xl border border-slate-300 px-3 py-2.5"
            required
          />
          <div className="mt-1 flex justify-between text-xs text-slate-500">
            <span>{errors.comments ? <span className="text-red-600">{errors.comments}</span> : "Cuanta mas precision, mejor propuesta recibiras."}</span>
            <span>{formData.comments.length}/{commentsMaxLength}</span>
          </div>
        </div>

        <div className="md:col-span-2">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={formData.privacyAccepted}
              onChange={(event) => updateField("privacyAccepted", event.target.checked)}
              required
            />
            Acepto la politica de privacidad y autorizo el contacto comercial.
          </label>
          {errors.privacyAccepted ? <p className="mt-1 text-sm text-red-600">{errors.privacyAccepted}</p> : null}
        </div>

        <div className="md:col-span-2 flex flex-col gap-3">
          <button
            type="submit"
            disabled={isSubmitting}
            className="w-full rounded-full bg-[var(--brand)] px-6 py-3 text-sm font-semibold text-white transition hover:bg-[var(--brand-strong)] disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isSubmitting ? "Enviando solicitud..." : "Enviar solicitud"}
          </button>

          {isSubmitted ? (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
              Gracias por contactar a TrackFlow. Nuestro equipo revisara tu operacion y te respondera con una propuesta en menos de 24 horas habiles.
            </div>
          ) : null}

          {isSubmitted && lowVolumeWarning ? (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              Para operaciones con menos de 100 envios/mes podemos proponer un plan de arranque progresivo antes de pasar al modelo full-service.
            </div>
          ) : null}
        </div>
      </form>
    </section>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-semibold text-slate-900">{label}</label>
      {children}
      {error ? <p className="mt-1 text-sm text-red-600">{error}</p> : null}
    </div>
  );
}
