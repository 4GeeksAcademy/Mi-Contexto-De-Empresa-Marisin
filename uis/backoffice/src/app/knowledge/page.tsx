"use client";

import { useState, type FormEvent } from "react";
import { ApiError } from "@/lib/api";
import { EXAMPLE_QUESTIONS, QUESTION_MAX_LENGTH, askKnowledgeBase } from "@/lib/knowledge";

type Status = "idle" | "loading" | "success" | "error";

// Asistente comercial (Hito 7 — RAG): los account managers de Miguel Torres preguntan
// por SLA, devoluciones, transportistas o tarifas y reciben la respuesta generada por el
// modelo a partir de la base de conocimiento (docs/company-knowledge-base/).
export default function KnowledgeAssistantPage() {
  const [question, setQuestion] = useState("");
  const [askedQuestion, setAskedQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>("idle");

  const trimmed = question.trim();
  const loading = status === "loading";

  async function ask(text: string) {
    const value = text.trim();
    if (value.length < 3 || loading) return;
    setStatus("loading");
    setError(null);
    setAnswer("");
    setAskedQuestion(value);
    try {
      setAnswer(await askKnowledgeBase(value));
      setStatus("success");
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 503) {
        setError("El asistente no está disponible ahora mismo. Inténtalo de nuevo en unos minutos.");
      } else if (reason instanceof ApiError && reason.status === 422) {
        setError("La pregunta debe tener entre 3 y 500 caracteres.");
      } else {
        setError(reason instanceof Error ? reason.message : "No se pudo consultar al asistente.");
      }
      setStatus("error");
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void ask(question);
  }

  return (
    <main className="min-h-[calc(100vh-57px)] bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">Asistente comercial</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            Respuestas sobre SLA de entrega, devoluciones, transportistas y tarifas de almacenamiento,
            redactadas a partir de los acuerdos estándar de TrackFlow. Lo que no esté documentado
            requiere aprobación: el asistente no lo promete.
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-3 rounded-lg border border-gray-200 bg-white p-4 shadow dark:border-gray-800 dark:bg-gray-900"
        >
          <label htmlFor="knowledge-question" className="block text-sm font-medium">
            Pregunta del cliente
          </label>
          <textarea
            id="knowledge-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void ask(question);
              }
            }}
            rows={3}
            maxLength={QUESTION_MAX_LENGTH}
            disabled={loading}
            placeholder="Ej.: ¿Cuál es la ventana de devolución estándar?"
            className="w-full resize-y rounded-md border border-gray-300 bg-white p-3 text-sm text-gray-900 placeholder:text-gray-400 focus:border-gray-900 focus:outline-none focus:ring-1 focus:ring-gray-900 disabled:opacity-60 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-100 dark:focus:border-gray-300 dark:focus:ring-gray-300"
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <span className="text-xs text-gray-500 dark:text-gray-400">
              {question.length}/{QUESTION_MAX_LENGTH} · Enter para enviar, Mayús+Enter para salto de línea
            </span>
            <button
              type="submit"
              disabled={loading || trimmed.length < 3}
              className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-gray-300"
            >
              {loading ? "Consultando…" : "Preguntar"}
            </button>
          </div>
          <div className="flex flex-wrap gap-2" aria-label="Preguntas de ejemplo">
            {EXAMPLE_QUESTIONS.map((example) => (
              <button
                key={example}
                type="button"
                disabled={loading}
                onClick={() => {
                  setQuestion(example);
                  void ask(example);
                }}
                className="rounded-full border border-gray-300 px-3 py-1 text-xs text-gray-700 transition-colors hover:bg-gray-100 disabled:opacity-50 dark:border-gray-700 dark:text-gray-300 dark:hover:bg-gray-800"
              >
                {example}
              </button>
            ))}
          </div>
        </form>

        {loading && (
          <p
            role="status"
            aria-live="polite"
            className="rounded-lg border border-gray-200 bg-white p-4 text-sm text-gray-600 shadow dark:border-gray-800 dark:bg-gray-900 dark:text-gray-300"
          >
            Buscando en la base de conocimiento y redactando la respuesta…
          </p>
        )}

        {status === "error" && error && (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
          >
            <p className="font-medium">No se pudo obtener una respuesta</p>
            <p>{error}</p>
            <button
              type="button"
              onClick={() => void ask(askedQuestion)}
              className="mt-2 underline underline-offset-2"
            >
              Reintentar
            </button>
          </div>
        )}

        {status === "success" && (
          <section
            aria-live="polite"
            aria-label="Respuesta del asistente"
            className="space-y-2 rounded-lg border border-gray-200 bg-white p-4 shadow dark:border-gray-800 dark:bg-gray-900"
          >
            <p className="text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
              {askedQuestion}
            </p>
            <p className="whitespace-pre-line text-sm leading-relaxed">{answer}</p>
          </section>
        )}
      </div>
    </main>
  );
}
