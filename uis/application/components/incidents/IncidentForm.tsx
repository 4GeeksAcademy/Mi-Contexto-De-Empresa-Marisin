"use client";

import { FormEvent, useState } from "react";
import {
  createIncident,
  incidentBranches,
  incidentCategories,
  incidentOrigins,
  incidentStatuses,
  type IncidentBranch,
  type IncidentCategory,
  type IncidentOrigin,
  type IncidentStatus,
  type Incident,
} from "@/lib/incidents";

type FormState = {
  title: string;
  description: string;
  category: IncidentCategory;
  status: IncidentStatus;
  origin: IncidentOrigin;
  branch: IncidentBranch;
};

const initialForm: FormState = {
  title: "",
  description: "",
  category: "DELAYED_DELIVERY" as const,
  status: "open" as const,
  origin: "customer" as const,
  branch: "central" as const,
};

type FormErrors = Partial<Record<keyof FormState, string>>;

export function IncidentForm({ onCreated }: { onCreated?: (incident: Incident) => void }) {
  const [form, setForm] = useState<FormState>(initialForm);
  const [errors, setErrors] = useState<FormErrors>({});
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  function validate() {
    const nextErrors: FormErrors = {};
    if (!form.title.trim()) nextErrors.title = "Escribe un título.";
    if (!form.description.trim()) nextErrors.description = "Describe la incidencia.";
    if (!form.branch) nextErrors.branch = "Selecciona una sede.";
    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    if (!validate()) return;

    setIsSubmitting(true);
    try {
      const incident = await createIncident(form);
      setForm(initialForm);
      setErrors({});
      setMessage("Incidencia registrada correctamente.");
      onCreated?.(incident);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "No se pudo registrar la incidencia.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5 rounded-3xl border border-white/10 bg-[var(--panel)] p-5 shadow-xl shadow-black/25 md:p-6">
      {message ? <p role="status" className="rounded-xl border border-cyan-300/20 bg-cyan-300/10 p-3 text-sm text-cyan-100">{message}</p> : null}
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Título" error={errors.title}>
          <input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} className={inputClass} />
        </Field>
        <Field label="Categoría" error={errors.category}>
          <select value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value as FormState["category"] })} className={inputClass}>
            {incidentCategories.map((category) => <option key={category}>{category}</option>)}
          </select>
        </Field>
        <Field label="Descripción" error={errors.description} className="md:col-span-2">
          <textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} className={`${inputClass} min-h-28`} />
        </Field>
        <Field label="Estado" error={errors.status}>
          <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value as FormState["status"] })} className={inputClass}>
            {incidentStatuses.map((status) => <option key={status}>{status}</option>)}
          </select>
        </Field>
        <Field label="Origen" error={errors.origin}>
          <select value={form.origin} onChange={(event) => setForm({ ...form, origin: event.target.value as FormState["origin"] })} className={inputClass}>
            {incidentOrigins.map((origin) => <option key={origin}>{origin}</option>)}
          </select>
        </Field>
        <Field label="Sede" error={errors.branch} className={form.origin === "branch" ? "rounded-xl border border-amber-300/50 bg-amber-300/10 p-3 md:col-span-2" : "md:col-span-2"}>
          <select value={form.branch} onChange={(event) => setForm({ ...form, branch: event.target.value as FormState["branch"] })} className={inputClass}>
            {incidentBranches.map((branch) => <option key={branch}>{branch}</option>)}
          </select>
        </Field>
      </div>
      <button type="submit" disabled={isSubmitting} className="rounded-xl bg-[var(--accent)] px-4 py-2.5 font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50">
        {isSubmitting ? "Registrando..." : "Registrar incidencia"}
      </button>
    </form>
  );
}

const inputClass = "mt-1 w-full rounded-xl border border-slate-600 bg-[var(--panel-soft)] px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300";

function Field({ label, error, className = "", children }: { label: string; error?: string; className?: string; children: React.ReactNode }) {
  return <label className={`block text-sm text-slate-200 ${className}`}><span>{label}</span>{children}{error ? <span className="mt-1 block text-xs text-rose-300">{error}</span> : null}</label>;
}
