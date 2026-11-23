import { fetchWithAuth } from "./api";

// Contrato de /rfp/tickets (Hito 9 · Parte 1 — recepción y enrutamiento de RFPs).
// El POST responde 202 al momento; el pipeline corre en segundo plano y la UI
// consulta el estado con GET hasta que sale de "analizando".

export type RfpStatus = "analizando" | "descartado" | "analisis_completo" | string;

export const MAX_PDF_BYTES = 10 * 1024 * 1024;
export const POLL_INTERVAL_MS = 3000;

export interface RfpTicketSummary {
  ticket_id: number;
  rfp_id: string;
  status: RfpStatus;
  stage: string;
  original_filename: string;
  client_name: string | null;
  error_stage: string | null;
  ready_for_drafting: boolean;
  stale: boolean;
  created_at: string;
  updated_at: string;
}

export interface RfpTicketAccepted {
  ticket_id: number;
  rfp_id: string;
  status: RfpStatus;
  stage: string;
  original_filename: string;
  status_url: string;
}

export interface KeyAspect {
  topic: string;
  detail: string;
  evidence: string;
}

export interface DepartmentSection {
  department_id: "warehouse" | "lastmile" | "reverse";
  department_name: string;
  responsible: string;
  key_aspects: KeyAspect[];
  open_questions: string[];
  excerpts: string[];
  source: "llm" | "rules";
  warnings: string[];
}

export interface Classification {
  is_rfp: boolean;
  document_type: string;
  confidence: number;
  reason: string;
  source: "llm" | "rules";
}

export interface Readability {
  language?: string;
  word_count?: number;
  estimated_tokens?: number;
  estimated_llm_input_tokens?: number;
  flesch_kincaid_grade?: number;
  gunning_fog?: number;
  flesch_reading_ease?: number;
  fernandez_huerta?: number;
  cost_tier?: string;
  source?: string;
}

export interface RfpMetadata {
  client_name: string | null;
  client_reference: string | null;
  client_country: string | null;
  currency: string | null;
  services_requested: string[];
  monthly_volume: number | null;
  deadline: string | null;
  deadline_text: string | null;
  budget_range: string | null;
  contact: { name: string | null; role: string | null; email: string | null };
  departments_needed: string[];
  readability: Readability;
  source: string;
  warnings: string[];
}

export interface HandoffDepartment {
  department_id: string;
  department_name: string;
  responsible: string;
  ask: string;
  key_aspects: KeyAspect[];
  open_questions: string[];
}

export interface Handoff {
  contract: string;
  ticket_id: number;
  next_status: string;
  ready_for_drafting: boolean;
  summary: string;
  summary_source: string;
  departments: HandoffDepartment[];
  inactive_departments: { department_id: string; reason: string; evidence: string }[];
  unassigned_requests: { topic: string; evidence: string; ask: string }[];
  conflicts: { type: string; detail: string; departments: string[]; ask: string }[];
}

export interface RfpTicketDetail extends Omit<RfpTicketSummary, "client_name"> {
  raw_pdf_path: string;
  file_size_bytes: number;
  markdown_chars: number | null;
  classification: Classification | null;
  metadata: RfpMetadata | null;
  sections: DepartmentSection[];
  handoff: Handoff | null;
  error_message: string | null;
}

export const STATUS_LABELS: Record<string, string> = {
  analizando: "Analizando",
  descartado: "Descartado",
  analisis_completo: "Análisis completo",
};

export const STAGE_LABELS: Record<string, string> = {
  recibido: "PDF recibido",
  convirtiendo: "Convirtiendo PDF a Markdown",
  clasificando: "Clasificando el documento",
  extrayendo_metadatos: "Extrayendo metadatos y legibilidad",
  orquestando: "Repartiendo por departamento",
  analizando_departamentos: "Analizando por departamento",
  sintetizando: "Consolidando el resumen para Ventas",
  completado: "Completado",
  descartado: "Descartado por el clasificador",
  error: "Error",
};

export const SERVICE_LABELS: Record<string, string> = {
  warehousing: "Almacenamiento",
  last_mile: "Última milla",
  reverse_logistics: "Devoluciones",
};

export function isAnalyzing(ticket: Pick<RfpTicketSummary, "status" | "stage" | "stale">): boolean {
  return ticket.status === "analizando" && ticket.stage !== "error" && !ticket.stale;
}

export async function uploadRfp(file: File): Promise<RfpTicketAccepted> {
  return (await fetchWithAuth(`/rfp/tickets?filename=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/pdf" },
    body: file,
  })) as RfpTicketAccepted;
}

export async function listRfpTickets(): Promise<RfpTicketSummary[]> {
  const data = (await fetchWithAuth("/rfp/tickets")) as { tickets?: RfpTicketSummary[] };
  return Array.isArray(data.tickets) ? data.tickets : [];
}

export async function getRfpTicket(ticketId: number): Promise<RfpTicketDetail> {
  return (await fetchWithAuth(`/rfp/tickets/${ticketId}`)) as RfpTicketDetail;
}
