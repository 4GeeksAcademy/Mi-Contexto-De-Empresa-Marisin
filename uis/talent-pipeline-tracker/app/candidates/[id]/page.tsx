"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import CandidateNotes from "@/components/CandidateNotes";
import { getCandidateById, patchCandidate, updateCandidate } from "@/services/api";
import { Candidate, CandidateFormData } from "@/types";

type UiState = "loading" | "success" | "error";

const STATUS_OPTIONS = [
  "new",
  "in_progress",
  "interview",
  "offer",
  "hired",
  "rejected",
  "on_hold",
  "Activa",
  "Descartada",
];

const STAGE_OPTIONS = [
  "review",
  "screening",
  "technical",
  "final",
  "offer",
  "hired",
  "rejected",
  "Aplicacion",
  "Entrevista",
];

function formatDate(value?: string) {
  if (!value) return "Sin fecha de aplicacion";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin fecha de aplicacion";

  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function buildOptions(base: string[], current: string) {
  if (!current) return base;
  return base.includes(current) ? base : [current, ...base];
}

function toFormData(candidate: Candidate): CandidateFormData {
  return {
    name: candidate.name,
    email: candidate.email,
    phone: candidate.phone || "",
    position: candidate.position,
    linkedin: candidate.linkedin || "",
    cv_url: candidate.cv_url || "",
    years_of_experience: candidate.years_of_experience,
    status: candidate.status,
    stage: candidate.stage,
  };
}

export default function CandidateDetailPage() {
  const params = useParams<{ id: string }>();
  const candidateId = params?.id ? String(params.id) : "";

  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [uiState, setUiState] = useState<UiState>("loading");
  const [errorMessage, setErrorMessage] = useState("");

  const [isEditing, setIsEditing] = useState(false);
  const [editForm, setEditForm] = useState<CandidateFormData | null>(null);

  const [isPatching, setIsPatching] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [mutationError, setMutationError] = useState("");
  const [mutationSuccess, setMutationSuccess] = useState("");

  useEffect(() => {
    if (!candidateId) return;

    let isCancelled = false;

    const loadCandidate = async () => {
      setUiState("loading");
      setErrorMessage("");

      try {
        const data = await getCandidateById(candidateId);
        if (isCancelled) return;

        setCandidate(data);
        setEditForm(toFormData(data));
        setUiState("success");
      } catch (error) {
        if (isCancelled) return;
        setUiState("error");
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "No se pudo cargar el detalle de la candidatura"
        );
      }
    };

    void loadCandidate();

    return () => {
      isCancelled = true;
    };
  }, [candidateId]);

  const statusOptions = useMemo(
    () => buildOptions(STATUS_OPTIONS, candidate?.status || ""),
    [candidate?.status]
  );

  const stageOptions = useMemo(
    () => buildOptions(STAGE_OPTIONS, candidate?.stage || ""),
    [candidate?.stage]
  );

  const handleStatusChange = async (nextStatus: string) => {
    if (!candidate) return;
    if (candidate.status === nextStatus) return;

    const previous = candidate;
    const nextCandidate = { ...candidate, status: nextStatus };

    setMutationError("");
    setMutationSuccess("");
    setCandidate(nextCandidate);

    try {
      setIsPatching(true);
      const updated = await patchCandidate(
        candidate.id,
        { status: nextStatus },
        candidate
      );
      setCandidate(updated);
      setEditForm(toFormData(updated));
      setMutationSuccess("Estado actualizado correctamente.");
    } catch (error) {
      setCandidate(previous);
      setMutationError(
        error instanceof Error ? error.message : "No se pudo actualizar el estado"
      );
    } finally {
      setIsPatching(false);
    }
  };

  const handleStageChange = async (nextStage: string) => {
    if (!candidate) return;
    if (candidate.stage === nextStage) return;

    const previous = candidate;
    const nextCandidate = { ...candidate, stage: nextStage };

    setMutationError("");
    setMutationSuccess("");
    setCandidate(nextCandidate);

    try {
      setIsPatching(true);
      const updated = await patchCandidate(
        candidate.id,
        { stage: nextStage },
        candidate
      );
      setCandidate(updated);
      setEditForm(toFormData(updated));
      setMutationSuccess("Etapa actualizada correctamente.");
    } catch (error) {
      setCandidate(previous);
      setMutationError(
        error instanceof Error ? error.message : "No se pudo actualizar la etapa"
      );
    } finally {
      setIsPatching(false);
    }
  };

  const handleEditSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!candidate || !editForm) return;

    setMutationError("");
    setMutationSuccess("");

    const payload: CandidateFormData = {
      ...editForm,
      name: editForm.name.trim(),
      email: editForm.email.trim(),
      position: editForm.position.trim(),
      status: editForm.status.trim(),
      stage: editForm.stage.trim(),
      phone: editForm.phone?.trim() || undefined,
      linkedin: editForm.linkedin?.trim() || undefined,
      cv_url: editForm.cv_url?.trim() || undefined,
      years_of_experience: editForm.years_of_experience,
    };

    if (
      !payload.name ||
      !payload.email ||
      !payload.position ||
      !payload.status ||
      !payload.stage
    ) {
      setMutationError("Completa todos los campos obligatorios del formulario.");
      return;
    }

    if (!payload.email.includes("@")) {
      setMutationError("El email no tiene un formato valido.");
      return;
    }

    try {
      setIsUpdating(true);
      const updated = await updateCandidate(candidate.id, payload);
      setCandidate(updated);
      setEditForm(toFormData(updated));
      setIsEditing(false);
      setMutationSuccess("Candidatura actualizada correctamente.");
    } catch (error) {
      setMutationError(
        error instanceof Error
          ? error.message
          : "No se pudo actualizar la candidatura"
      );
    } finally {
      setIsUpdating(false);
    }
  };

  return (
    <div className="min-h-screen bg-[linear-gradient(160deg,#f8fafc_0%,#e2e8f0_42%,#f1f5f9_100%)] px-4 py-8 text-slate-900 sm:px-6 lg:px-10">
      <main className="mx-auto w-full max-w-6xl space-y-6">
        <header className="rounded-2xl border border-slate-200/80 bg-white/95 p-6 shadow-lg shadow-slate-200/70 backdrop-blur sm:p-8">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-700">
                TrackFlow · People & Talent
              </p>
              <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
                Detalle de Candidatura
              </h1>
              <p className="mt-1 text-sm text-slate-600">
                Seguimiento individual del pipeline de seleccion.
              </p>
            </div>

            <Link
              href="/"
              className="inline-flex items-center justify-center rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
            >
              Volver al listado
            </Link>
          </div>
        </header>

        {uiState === "loading" && (
          <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
            <div className="mb-5 flex items-center gap-3 text-slate-700">
              <span className="h-5 w-5 animate-spin rounded-full border-2 border-cyan-700 border-t-transparent" />
              <p className="font-medium">Cargando detalle de candidatura...</p>
            </div>
            <div className="space-y-3">
              {[1, 2, 3].map((item) => (
                <div key={item} className="h-4 animate-pulse rounded bg-slate-200" />
              ))}
            </div>
          </section>
        )}

        {uiState === "error" && (
          <section className="rounded-2xl border border-red-200 bg-red-50 p-6 text-red-900 shadow-sm">
            <h2 className="text-lg font-semibold">Error al cargar el detalle</h2>
            <p className="mt-2 text-sm">{errorMessage}</p>
          </section>
        )}

        {!candidateId && (
          <section className="rounded-2xl border border-red-200 bg-red-50 p-6 text-red-900 shadow-sm">
            <h2 className="text-lg font-semibold">ID de candidatura no valido</h2>
            <p className="mt-2 text-sm">
              No se encontro el identificador en la URL para cargar el detalle.
            </p>
          </section>
        )}

        {uiState === "success" && candidate && (
          <>
            <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
              <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <h2 className="text-2xl font-semibold text-slate-900">
                  {candidate.name}
                </h2>
                <button
                  type="button"
                  onClick={() => setIsEditing((prev) => !prev)}
                  className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-800"
                >
                  {isEditing ? "Cerrar Edicion" : "Editar Candidatura"}
                </button>
              </div>

              {mutationSuccess && (
                <p className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                  {mutationSuccess}
                </p>
              )}

              {mutationError && (
                <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                  {mutationError}
                </p>
              )}

              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Nombre completo
                  </p>
                  <p className="mt-1 text-sm text-slate-900">{candidate.name}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Email
                  </p>
                  <p className="mt-1 text-sm text-slate-900">{candidate.email}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Telefono
                  </p>
                  <p className="mt-1 text-sm text-slate-900">{candidate.phone || "No informado"}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Puesto
                  </p>
                  <p className="mt-1 text-sm text-slate-900">{candidate.position}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    LinkedIn
                  </p>
                  {candidate.linkedin ? (
                    <a
                      href={candidate.linkedin}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-1 inline-block text-sm font-medium text-cyan-700 underline-offset-2 hover:underline"
                    >
                      Abrir perfil
                    </a>
                  ) : (
                    <p className="mt-1 text-sm text-slate-900">No informado</p>
                  )}
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    CV
                  </p>
                  {candidate.cv_url ? (
                    <a
                      href={candidate.cv_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-1 inline-block text-sm font-medium text-cyan-700 underline-offset-2 hover:underline"
                    >
                      Ver curriculum
                    </a>
                  ) : (
                    <p className="mt-1 text-sm text-slate-900">No informado</p>
                  )}
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Anos de experiencia
                  </p>
                  <p className="mt-1 text-sm text-slate-900">
                    {candidate.years_of_experience ?? "No informado"}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                    Fecha de aplicacion
                  </p>
                  <p className="mt-1 text-sm text-slate-900">
                    {formatDate(candidate.applied_at || candidate.created_at)}
                  </p>
                </div>
              </div>

              <div className="mt-5 grid gap-4 md:grid-cols-2">
                <label className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-slate-700">Estado actual</span>
                  <select
                    value={candidate.status}
                    onChange={(event) => void handleStatusChange(event.target.value)}
                    disabled={isPatching}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {statusOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex flex-col gap-1">
                  <span className="text-sm font-medium text-slate-700">Etapa actual</span>
                  <select
                    value={candidate.stage}
                    onChange={(event) => void handleStageChange(event.target.value)}
                    disabled={isPatching}
                    className="rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-cyan-500 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {stageOptions.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
            </section>

            {isEditing && editForm && (
              <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
                <h2 className="text-xl font-semibold text-slate-900">
                  Editar Datos de Candidatura
                </h2>
                <p className="mt-1 text-sm text-slate-600">
                  Actualiza la informacion principal del perfil.
                </p>

                <form onSubmit={handleEditSubmit} className="mt-4 grid gap-4">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <label className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-slate-700">Nombre completo *</span>
                      <input
                        type="text"
                        value={editForm.name}
                        onChange={(event) =>
                          setEditForm((prev) =>
                            prev ? { ...prev, name: event.target.value } : prev
                          )
                        }
                        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                      />
                    </label>

                    <label className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-slate-700">Email *</span>
                      <input
                        type="email"
                        value={editForm.email}
                        onChange={(event) =>
                          setEditForm((prev) =>
                            prev ? { ...prev, email: event.target.value } : prev
                          )
                        }
                        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                      />
                    </label>

                    <label className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-slate-700">Telefono</span>
                      <input
                        type="text"
                        value={editForm.phone || ""}
                        onChange={(event) =>
                          setEditForm((prev) =>
                            prev ? { ...prev, phone: event.target.value } : prev
                          )
                        }
                        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                      />
                    </label>

                    <label className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-slate-700">Puesto *</span>
                      <input
                        type="text"
                        value={editForm.position}
                        onChange={(event) =>
                          setEditForm((prev) =>
                            prev ? { ...prev, position: event.target.value } : prev
                          )
                        }
                        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                      />
                    </label>

                    <label className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-slate-700">LinkedIn</span>
                      <input
                        type="url"
                        value={editForm.linkedin || ""}
                        onChange={(event) =>
                          setEditForm((prev) =>
                            prev ? { ...prev, linkedin: event.target.value } : prev
                          )
                        }
                        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                      />
                    </label>

                    <label className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-slate-700">CV URL</span>
                      <input
                        type="url"
                        value={editForm.cv_url || ""}
                        onChange={(event) =>
                          setEditForm((prev) =>
                            prev ? { ...prev, cv_url: event.target.value } : prev
                          )
                        }
                        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                      />
                    </label>

                    <label className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-slate-700">Estado *</span>
                      <input
                        type="text"
                        value={editForm.status}
                        onChange={(event) =>
                          setEditForm((prev) =>
                            prev ? { ...prev, status: event.target.value } : prev
                          )
                        }
                        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                      />
                    </label>

                    <label className="flex flex-col gap-1">
                      <span className="text-sm font-medium text-slate-700">Etapa *</span>
                      <input
                        type="text"
                        value={editForm.stage}
                        onChange={(event) =>
                          setEditForm((prev) =>
                            prev ? { ...prev, stage: event.target.value } : prev
                          )
                        }
                        className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                      />
                    </label>
                  </div>

                  <label className="flex flex-col gap-1">
                    <span className="text-sm font-medium text-slate-700">Anos de experiencia</span>
                    <input
                      type="number"
                      min={0}
                      value={editForm.years_of_experience ?? ""}
                      onChange={(event) =>
                        setEditForm((prev) =>
                          prev
                            ? {
                                ...prev,
                                years_of_experience:
                                  event.target.value === ""
                                    ? undefined
                                    : Number(event.target.value),
                              }
                            : prev
                        )
                      }
                      className="rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-cyan-500"
                    />
                  </label>

                  <div className="mt-2 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
                    <button
                      type="button"
                      onClick={() => {
                        if (!candidate) return;
                        setEditForm(toFormData(candidate));
                        setIsEditing(false);
                      }}
                      className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-100"
                    >
                      Cancelar
                    </button>
                    <button
                      type="submit"
                      disabled={isUpdating}
                      className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isUpdating ? "Guardando cambios..." : "Guardar cambios"}
                    </button>
                  </div>
                </form>
              </section>
            )}

            <CandidateNotes candidateId={candidateId} />
          </>
        )}
      </main>
    </div>
  );
}