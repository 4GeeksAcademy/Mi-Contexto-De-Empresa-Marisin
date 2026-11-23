"use client";

import { useCallback, useEffect, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { ApiError } from "@/lib/api";
import {
  MAX_PDF_BYTES,
  POLL_INTERVAL_MS,
  SERVICE_LABELS,
  STAGE_LABELS,
  STATUS_LABELS,
  getRfpTicket,
  isAnalyzing,
  listRfpTickets,
  uploadRfp,
  type RfpTicketDetail,
  type RfpTicketSummary,
} from "@/lib/rfp";

const CARD = "rounded-lg border border-gray-200 bg-white p-4 shadow dark:border-gray-800 dark:bg-gray-900";
const MUTED = "text-gray-500 dark:text-gray-400";

const STATUS_STYLES: Record<string, string> = {
  analizando: "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200",
  descartado: "bg-gray-200 text-gray-800 dark:bg-gray-800 dark:text-gray-200",
  analisis_completo: "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200",
};

function StatusBadge({ ticket }: { ticket: Pick<RfpTicketSummary, "status" | "stage" | "stale"> }) {
  const failed = ticket.stage === "error";
  const label = failed ? "Error" : ticket.stale ? "Sin actividad" : STATUS_LABELS[ticket.status] ?? ticket.status;
  const style = failed || ticket.stale
    ? "bg-red-100 text-red-900 dark:bg-red-900/40 dark:text-red-200"
    : STATUS_STYLES[ticket.status] ?? STATUS_STYLES.descartado;
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>{label}</span>;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("es-ES");
}

function Field({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <dt className={`text-xs uppercase tracking-wide ${MUTED}`}>{label}</dt>
      <dd className="text-sm">{value === null || value === undefined || value === "" ? "—" : value}</dd>
    </div>
  );
}

function TicketDetail({ ticket }: { ticket: RfpTicketDetail }) {
  const metadata = ticket.metadata;
  const handoff = ticket.handoff;
  const readability = metadata?.readability;
  const sections = handoff?.departments ?? [];

  return (
    <section aria-label={`Ticket ${ticket.ticket_id}`} className="space-y-4">
      <div className={`${CARD} space-y-2`}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">
            Ticket #{ticket.ticket_id} · {ticket.original_filename}
          </h2>
          <StatusBadge ticket={ticket} />
        </div>
        <p className={`text-sm ${MUTED}`}>
          Etapa: {STAGE_LABELS[ticket.stage] ?? ticket.stage} · Actualizado {formatDate(ticket.updated_at)} · PDF en{" "}
          <code className="text-xs">{ticket.raw_pdf_path}</code>
          {ticket.markdown_chars ? ` · Markdown de ${ticket.markdown_chars.toLocaleString("es-ES")} caracteres` : ""}
        </p>
        {isAnalyzing(ticket) && (
          <p role="status" aria-live="polite" className="text-sm text-amber-800 dark:text-amber-200">
            Analizando: {STAGE_LABELS[ticket.stage] ?? ticket.stage}… (se actualiza solo)
          </p>
        )}
      </div>

      {ticket.stage === "error" && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          <p className="font-medium">
            El análisis falló en la etapa «{STAGE_LABELS[ticket.error_stage ?? ""] ?? ticket.error_stage}».
          </p>
          <p className="break-words">{ticket.error_message}</p>
          <p className="mt-2">
            Reprocesar: <code>python scripts/rfp_intake_run.py --ticket-id {ticket.ticket_id}</code>
          </p>
        </div>
      )}
      {ticket.stale && ticket.stage !== "error" && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          El ticket lleva un rato sin avanzar: el proceso pudo detenerse. Reprocesa con{" "}
          <code>python scripts/rfp_intake_run.py --ticket-id {ticket.ticket_id}</code>.
        </div>
      )}

      {ticket.classification && (
        <div className={`${CARD} text-sm`}>
          <p className="font-medium">
            Clasificador: {ticket.classification.is_rfp ? "RFP válida" : "No es una RFP"} ({ticket.classification.document_type},
            confianza {Math.round(ticket.classification.confidence * 100)} %, {ticket.classification.source === "llm" ? "LLM" : "reglas"})
          </p>
          <p className={MUTED}>{ticket.classification.reason}</p>
        </div>
      )}

      {handoff && (
        <div className={`${CARD} space-y-2`}>
          <h3 className="font-semibold">Resumen para Ventas</h3>
          <p className="text-sm leading-relaxed">{handoff.summary}</p>
          <p className={`text-xs ${MUTED}`}>
            Handoff <code>{handoff.contract}</code> ·{" "}
            {handoff.ready_for_drafting ? `listo para la Parte 2 (${handoff.next_status})` : "sin departamentos activos"}
          </p>
        </div>
      )}

      {metadata && (
        <div className={CARD}>
          <h3 className="mb-3 font-semibold">Metadatos de la RFP</h3>
          <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Field label="Cliente" value={metadata.client_name} />
            <Field label="País" value={metadata.client_country} />
            <Field label="Moneda" value={metadata.currency} />
            <Field label="Referencia" value={metadata.client_reference} />
            <Field
              label="Servicios"
              value={metadata.services_requested.map((service) => SERVICE_LABELS[service] ?? service).join(", ")}
            />
            <Field label="Volumen mensual" value={metadata.monthly_volume?.toLocaleString("es-ES") ?? "No indicado"} />
            <Field label="Fecha límite" value={metadata.deadline ?? metadata.deadline_text} />
            <Field label="Presupuesto" value={metadata.budget_range} />
            <Field
              label="Contacto"
              value={[metadata.contact?.name, metadata.contact?.role, metadata.contact?.email].filter(Boolean).join(" · ")}
            />
            <Field label="Extracción" value={metadata.source === "llm" ? "LLM + guardas" : "Reglas"} />
          </dl>
          {readability && (
            <div className="mt-4 border-t border-gray-200 pt-3 dark:border-gray-800">
              <h4 className="mb-2 text-sm font-medium">Legibilidad y costo de procesamiento</h4>
              <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <Field label="Costo estimado" value={readability.cost_tier} />
                <Field label="Tokens del documento" value={readability.estimated_tokens} />
                <Field label="Tokens de entrada LLM" value={readability.estimated_llm_input_tokens} />
                <Field label="Palabras" value={readability.word_count} />
                <Field label="Flesch-Kincaid" value={readability.flesch_kincaid_grade} />
                <Field label="Gunning Fog" value={readability.gunning_fog} />
                <Field label="Fernández Huerta" value={readability.fernandez_huerta} />
                <Field label="Idioma / fuente" value={`${readability.language ?? "—"} / ${readability.source ?? "—"}`} />
              </dl>
            </div>
          )}
          {metadata.warnings.length > 0 && (
            <details className={`mt-3 text-xs ${MUTED}`}>
              <summary>Avisos de las guardas ({metadata.warnings.length})</summary>
              <ul className="ml-4 list-disc">
                {metadata.warnings.map((warning) => <li key={warning}>{warning}</li>)}
              </ul>
            </details>
          )}
        </div>
      )}

      {sections.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-semibold">Qué pedir a quién</h3>
          <div className="grid gap-3 md:grid-cols-2">
            {sections.map((section) => (
              <article key={section.department_id} className={`${CARD} space-y-2`}>
                <header>
                  <p className={`text-xs uppercase tracking-wide ${MUTED}`}>
                    {section.department_name} · <code>{section.department_id}</code>
                  </p>
                  <p className="text-base font-semibold">{section.responsible}</p>
                  <p className="text-sm">{section.ask}</p>
                </header>
                <div>
                  <p className="text-sm font-medium">Aspectos clave</p>
                  <ul className="ml-4 list-disc space-y-1 text-sm">
                    {section.key_aspects.map((aspect, index) => (
                      <li key={`${aspect.topic}-${index}`}>
                        <span className="font-medium">{aspect.topic}:</span> {aspect.detail}
                        <span className={`block text-xs italic ${MUTED}`}>«{aspect.evidence}»</span>
                      </li>
                    ))}
                  </ul>
                </div>
                {section.open_questions.length > 0 && (
                  <div>
                    <p className="text-sm font-medium">Preguntas abiertas para el cliente</p>
                    <ul className="ml-4 list-disc text-sm">
                      {section.open_questions.map((question) => <li key={question}>{question}</li>)}
                    </ul>
                  </div>
                )}
              </article>
            ))}
          </div>
        </div>
      )}

      {handoff && (handoff.inactive_departments.length > 0 || handoff.unassigned_requests.length > 0 || handoff.conflicts.length > 0) && (
        <div className={`${CARD} space-y-2 text-sm`}>
          {handoff.inactive_departments.length > 0 && (
            <div>
              <p className="font-medium">Departamentos sin participación</p>
              <ul className="ml-4 list-disc">
                {handoff.inactive_departments.map((item) => (
                  <li key={item.department_id}>
                    <code>{item.department_id}</code>: {item.reason}
                    {item.evidence && <span className={`italic ${MUTED}`}> — «{item.evidence}»</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {handoff.unassigned_requests.length > 0 && (
            <div>
              <p className="font-medium">Peticiones sin departamento (coordina Miguel Torres)</p>
              <ul className="ml-4 list-disc">
                {handoff.unassigned_requests.map((item) => (
                  <li key={item.topic}>{item.topic}{item.evidence && <span className={`italic ${MUTED}`}> — «{item.evidence}»</span>}</li>
                ))}
              </ul>
            </div>
          )}
          {handoff.conflicts.length > 0 && (
            <div className="text-red-800 dark:text-red-200">
              <p className="font-medium">Contradicciones a revisar</p>
              <ul className="ml-4 list-disc">
                {handoff.conflicts.map((conflict) => (
                  <li key={`${conflict.type}-${conflict.detail}`}>
                    <code>{conflict.type}</code>: {conflict.detail} (decide {conflict.ask})
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// Recepción de RFPs (Hito 9 · Parte 1): Ventas sube el PDF, se crea un ticket y la
// página consulta su estado hasta que el pipeline termina (descartado o análisis completo).
export default function RfpIntakePage() {
  const [tickets, setTickets] = useState<RfpTicketSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<RfpTicketDetail | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await listRfpTickets();
      setTickets(list);
      if (selectedId !== null) setDetail(await getRfpTicket(selectedId));
    } catch (reason: unknown) {
      if (reason instanceof ApiError && reason.status === 503) {
        setError("La recepción de RFPs no está disponible (¿falta DATABASE_URL en la API?).");
      } else {
        setError(reason instanceof Error ? reason.message : "No se pudieron cargar los tickets.");
      }
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const polling = tickets.some(isAnalyzing) || (detail !== null && isAnalyzing(detail));
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [polling, refresh]);

  function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const chosen = event.target.files?.[0] ?? null;
    setMessage(null);
    setError(null);
    if (chosen && !chosen.name.toLowerCase().endsWith(".pdf")) {
      setError("Las RFPs se suben siempre en PDF.");
      setFile(null);
      return;
    }
    if (chosen && chosen.size > MAX_PDF_BYTES) {
      setError("El PDF supera el máximo de 10 MB.");
      setFile(null);
      return;
    }
    setFile(chosen);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file || uploading) return;
    setUploading(true);
    setError(null);
    setMessage(null);
    try {
      const accepted = await uploadRfp(file);
      setMessage(`Ticket #${accepted.ticket_id} creado: analizando «${accepted.original_filename}»…`);
      setSelectedId(accepted.ticket_id);
      setFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "No se pudo subir la RFP.");
    } finally {
      setUploading(false);
    }
  }

  return (
    <main className="min-h-[calc(100vh-57px)] bg-gray-50 text-gray-900 dark:bg-gray-950 dark:text-gray-100">
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold">Recepción de RFPs</h1>
          <p className={`text-sm ${MUTED}`}>
            Sube la RFP del cliente en PDF. Se crea un ticket, el documento se convierte a Markdown, el clasificador
            decide si es una RFP y, si lo es, cada departamento (Warehouse, Last Mile, Reverse) recibe solo lo que le
            toca. Al terminar verás qué pedir a quién sin abrir el PDF.
          </p>
        </div>

        <form onSubmit={handleSubmit} className={`${CARD} flex flex-wrap items-end gap-3`}>
          <div className="min-w-64 flex-1">
            <label htmlFor="rfp-file" className="block text-sm font-medium">RFP en PDF</label>
            <input
              id="rfp-file"
              ref={inputRef}
              type="file"
              accept="application/pdf,.pdf"
              onChange={handleFile}
              disabled={uploading}
              className="mt-1 block w-full text-sm file:mr-3 file:rounded-md file:border-0 file:bg-gray-900 file:px-3 file:py-2 file:text-white dark:file:bg-gray-100 dark:file:text-gray-900"
            />
          </div>
          <button
            type="submit"
            disabled={!file || uploading}
            className="rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-gray-300"
          >
            {uploading ? "Subiendo…" : "Subir RFP"}
          </button>
        </form>

        {message && <p role="status" className="text-sm text-emerald-800 dark:text-emerald-200">{message}</p>}
        {error && (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
            {error}
          </p>
        )}

        <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
          <section aria-label="Tickets de RFP" className={`${CARD} h-fit`}>
            <div className="mb-2 flex items-center justify-between">
              <h2 className="font-semibold">Tickets</h2>
              <button type="button" onClick={() => void refresh()} className="text-xs underline underline-offset-2">
                Actualizar
              </button>
            </div>
            {tickets.length === 0 ? (
              <p className={`text-sm ${MUTED}`}>Aún no hay RFPs subidas.</p>
            ) : (
              <ul className="divide-y divide-gray-200 dark:divide-gray-800">
                {tickets.map((ticket) => (
                  <li key={ticket.ticket_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(ticket.ticket_id)}
                      aria-current={ticket.ticket_id === selectedId ? "true" : undefined}
                      className={`w-full space-y-1 px-2 py-2 text-left text-sm transition-colors hover:bg-gray-100 dark:hover:bg-gray-800 ${
                        ticket.ticket_id === selectedId ? "bg-gray-100 dark:bg-gray-800" : ""
                      }`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="font-medium">#{ticket.ticket_id} {ticket.client_name ?? ticket.original_filename}</span>
                        <StatusBadge ticket={ticket} />
                      </span>
                      <span className={`block text-xs ${MUTED}`}>
                        {STAGE_LABELS[ticket.stage] ?? ticket.stage} · {formatDate(ticket.created_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <div>
            {detail ? (
              <TicketDetail ticket={detail} />
            ) : (
              <p className={`${CARD} text-sm ${MUTED}`}>Selecciona un ticket para ver su análisis.</p>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
