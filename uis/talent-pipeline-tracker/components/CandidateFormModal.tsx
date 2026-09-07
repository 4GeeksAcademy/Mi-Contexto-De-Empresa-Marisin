"use client";

import { FormEvent, useMemo, useState } from "react";
import { createCandidate } from "@/services/api";
import { CandidateFormData } from "@/types";

interface CandidateFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: () => void;
}

const initialFormData: CandidateFormData = {
  name: "",
  email: "",
  phone: "",
  position: "",
  linkedin: "",
  cv_url: "",
  years_of_experience: undefined,
  status: "Activa",
  stage: "Aplicación",
};

export default function CandidateFormModal({
  isOpen,
  onClose,
  onCreated,
}: CandidateFormModalProps) {
  const [formData, setFormData] = useState<CandidateFormData>(initialFormData);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const trimmedForm = useMemo(
    () => ({
      ...formData,
      name: formData.name.trim(),
      email: formData.email.trim(),
      position: formData.position.trim(),
      status: formData.status.trim(),
      stage: formData.stage.trim(),
      phone: formData.phone?.trim() || undefined,
      linkedin: formData.linkedin?.trim() || undefined,
      cv_url: formData.cv_url?.trim() || undefined,
    }),
    [formData]
  );

  if (!isOpen) return null;

  const handleClose = () => {
    if (isSubmitting) return;
    setErrorMessage("");
    setFormData(initialFormData);
    onClose();
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setErrorMessage("");

    if (
      !trimmedForm.name ||
      !trimmedForm.email ||
      !trimmedForm.position ||
      !trimmedForm.status ||
      !trimmedForm.stage
    ) {
      setErrorMessage("Completa los campos requeridos para registrar la candidatura.");
      return;
    }

    if (!trimmedForm.email.includes("@")) {
      setErrorMessage("El email no tiene un formato válido.");
      return;
    }

    try {
      setIsSubmitting(true);
      await createCandidate(trimmedForm);
      setFormData(initialFormData);
      onCreated();
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "No se pudo registrar la candidatura"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/55 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="candidate-form-title"
    >
      <div className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-2xl sm:p-7">
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 id="candidate-form-title" className="text-2xl font-bold text-slate-900">
              Registrar Nueva Candidatura
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              Alta interna del pipeline de People & Talent de TrackFlow.
            </p>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
          >
            Cerrar
          </button>
        </div>

        <form onSubmit={handleSubmit} className="grid gap-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700">Nombre completo *</span>
              <input
                type="text"
                value={formData.name}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, name: event.target.value }))
                }
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700">Email *</span>
              <input
                type="email"
                value={formData.email}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, email: event.target.value }))
                }
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700">Teléfono</span>
              <input
                type="text"
                value={formData.phone}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, phone: event.target.value }))
                }
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700">Puesto *</span>
              <input
                type="text"
                value={formData.position}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, position: event.target.value }))
                }
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700">Estado *</span>
              <input
                type="text"
                value={formData.status}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, status: event.target.value }))
                }
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700">Etapa *</span>
              <input
                type="text"
                value={formData.stage}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, stage: event.target.value }))
                }
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700">LinkedIn</span>
              <input
                type="url"
                value={formData.linkedin}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, linkedin: event.target.value }))
                }
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
              />
            </label>

            <label className="flex flex-col gap-1">
              <span className="text-sm font-medium text-slate-700">CV URL</span>
              <input
                type="url"
                value={formData.cv_url}
                onChange={(event) =>
                  setFormData((prev) => ({ ...prev, cv_url: event.target.value }))
                }
                className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
              />
            </label>
          </div>

          <label className="flex flex-col gap-1">
            <span className="text-sm font-medium text-slate-700">
              Años de experiencia
            </span>
            <input
              type="number"
              min={0}
              value={formData.years_of_experience ?? ""}
              onChange={(event) =>
                setFormData((prev) => ({
                  ...prev,
                  years_of_experience:
                    event.target.value === ""
                      ? undefined
                      : Number(event.target.value),
                }))
              }
              className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
            />
          </label>

          {errorMessage && (
            <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {errorMessage}
            </p>
          )}

          <div className="mt-2 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              type="button"
              onClick={handleClose}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isSubmitting ? "Guardando..." : "Guardar Candidatura"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}