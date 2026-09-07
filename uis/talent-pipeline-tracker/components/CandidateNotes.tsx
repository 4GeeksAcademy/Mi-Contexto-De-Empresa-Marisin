"use client";

import { FormEvent, useEffect, useState } from "react";
import { addNote, deleteNote, getNotes } from "@/services/api";
import { Note } from "@/types";

interface CandidateNotesProps {
  candidateId: string;
}

type NotesState = "loading" | "success" | "error";

function formatDate(value?: string) {
  if (!value) return "Sin fecha";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin fecha";

  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export default function CandidateNotes({ candidateId }: CandidateNotesProps) {
  const [notes, setNotes] = useState<Note[]>([]);
  const [notesState, setNotesState] = useState<NotesState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [draftNote, setDraftNote] = useState("");
  const [isSavingNote, setIsSavingNote] = useState(false);
  const [deletingNoteId, setDeletingNoteId] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState("");

  useEffect(() => {
    let isCancelled = false;

    const loadNotes = async () => {
      setNotesState("loading");
      setErrorMessage("");

      try {
        const data = await getNotes(candidateId);
        if (isCancelled) return;

        setNotes(data);
        setNotesState("success");
      } catch (error) {
        if (isCancelled) return;

        setNotesState("error");
        setErrorMessage(
          error instanceof Error
            ? error.message
            : "No se pudieron cargar las notas internas"
        );
      }
    };

    void loadNotes();

    return () => {
      isCancelled = true;
    };
  }, [candidateId]);

  const handleAddNote = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setFeedbackMessage("");
    setErrorMessage("");

    const content = draftNote.trim();
    if (!content) {
      setErrorMessage("La nota no puede estar vacia.");
      return;
    }

    try {
      setIsSavingNote(true);
      const created = await addNote(candidateId, content);
      setNotes((prev) => [created, ...prev]);
      setDraftNote("");
      setFeedbackMessage("Nota interna agregada correctamente.");
      setNotesState("success");
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "No se pudo agregar la nota"
      );
    } finally {
      setIsSavingNote(false);
    }
  };

  const handleDeleteNote = async (noteId: string | number) => {
    setFeedbackMessage("");
    setErrorMessage("");

    const normalizedId = String(noteId);

    try {
      setDeletingNoteId(normalizedId);
      await deleteNote(candidateId, noteId);
      setNotes((prev) => prev.filter((item) => String(item.id) !== normalizedId));
      setFeedbackMessage("Nota eliminada correctamente.");
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "No se pudo eliminar la nota"
      );
    } finally {
      setDeletingNoteId(null);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xl font-semibold text-slate-900">Notas Internas</h2>
      </div>

      <form onSubmit={handleAddNote} className="mb-5 grid gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-sm font-medium text-slate-700">
            Nueva nota para el equipo de People & Talent
          </span>
          <textarea
            value={draftNote}
            onChange={(event) => setDraftNote(event.target.value)}
            rows={3}
            className="rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-900 outline-none transition focus:border-cyan-500"
            placeholder="Ej: Pendiente confirmar disponibilidad para entrevista tecnica"
          />
        </label>
        <div>
          <button
            type="submit"
            disabled={isSavingNote}
            className="rounded-lg bg-cyan-700 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isSavingNote ? "Guardando nota..." : "Agregar nota"}
          </button>
        </div>
      </form>

      {feedbackMessage && (
        <p className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {feedbackMessage}
        </p>
      )}

      {errorMessage && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {errorMessage}
        </p>
      )}

      {notesState === "loading" && (
        <div className="space-y-3">
          {[1, 2].map((item) => (
            <div
              key={item}
              className="animate-pulse rounded-xl border border-slate-200 p-4"
            >
              <div className="h-3 w-1/3 rounded bg-slate-200" />
              <div className="mt-3 h-3 w-full rounded bg-slate-100" />
            </div>
          ))}
        </div>
      )}

      {notesState === "error" && !notes.length && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          Error al cargar notas internas.
        </div>
      )}

      {notesState === "success" && notes.length === 0 && (
        <p className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
          Aun no existen notas internas para esta candidatura.
        </p>
      )}

      {notes.length > 0 && (
        <ul className="space-y-3">
          {notes.map((note) => {
            const currentDeleting = deletingNoteId === String(note.id);

            return (
              <li
                key={note.id}
                className="rounded-xl border border-slate-200 bg-white p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                      Registrada el {formatDate(note.created_at)}
                    </p>
                    <p className="mt-2 text-sm text-slate-800">{note.content}</p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleDeleteNote(note.id)}
                    disabled={currentDeleting}
                    className="rounded-lg border border-red-300 px-3 py-1.5 text-xs font-semibold text-red-700 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {currentDeleting ? "Eliminando..." : "Eliminar"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}