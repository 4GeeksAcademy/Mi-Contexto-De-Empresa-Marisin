import { fetchWithAuth } from "./api";

// Contrato de /rfp/tickets (Hito 9 · Partes 1 y 2 — recepción, enrutamiento y borradores).
// El POST responde 202 al momento; el pipeline corre en segundo plano y la UI
// consulta el estado con GET mientras haya trabajo en curso (análisis o borradores).

export type RfpStatus =
  | "analizando"
  | "descartado"
  | "analisis_completo"
  | "generando_borrador"
  | "en_evaluación"
  | "needs_human_review"
  | string;

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
  ready_for_approval?: boolean;
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
  // Parte 2: borrador de la sección y su evaluación.
  draft_content?: string | null;
  draft_status?: DraftStatus | null;
  draft_source?: "llm" | "rules" | null;
  iterations?: number;
  evaluation_results?: EvaluationResult | null;
  evaluation_history?: EvaluationHistoryEntry[];
}

export type DraftStatus = "generando_borrador" | "en_evaluación" | "evaluacion_superada" | "needs_human_review";

export interface ComplianceViolation {
  rule_id: string;
  detail: string;
  evidence: string;
}

// Forma del enunciado: readability / relevance / compliance + overall_pass + feedback.
export interface EvaluationResult {
  section_id: string;
  department_id: string;
  iteration: number;
  readability: { pass: boolean; score: number | null; details: Record<string, unknown> & { problems?: string[]; metric?: string } };
  relevance: { pass: boolean; missing_aspects: string[] };
  compliance: { pass: boolean; rule_ids: string[]; violations: ComplianceViolation[] };
  overall_pass: boolean;
  feedback_for_generator: string;
  evaluated_at: string;
}

export interface EvaluationHistoryEntry {
  iteration: number;
  draft_source: string;
  overall_pass: boolean;
  readability_pass: boolean;
  relevance_pass: boolean;
  compliance_pass: boolean;
  violations: string[];
  missing_aspects: string[];
  feedback_for_generator: string;
}

export interface DraftingHandoff {
  contract: string;
  status: string;
  next_status: string;
  currency: string | null;
  needs_human_review: string[];
  ready_for_approval: boolean;
  metrics: { max_iterations: number; avg_iterations: number; first_pass_sections: number; sections: number };
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
  drafting_handoff?: DraftingHandoff | null;
  error_message: string | null;
}

export const STATUS_LABELS: Record<string, string> = {
  analizando: "Analizando",
  descartado: "Descartado",
  analisis_completo: "Análisis completo",
  generando_borrador: "Generando borrador",
  "en_evaluación": "En evaluación",
  needs_human_review: "Revisión humana",
};

export const DRAFT_STATUS_LABELS: Record<string, string> = {
  generando_borrador: "Generando borrador",
  "en_evaluación": "Evaluando",
  evaluacion_superada: "Evaluación superada",
  needs_human_review: "Provisional · revisión humana",
};

export const COMPLIANCE_RULE_LABELS: Record<string, string> = {
  "currency-by-country": "Moneda según el país",
  "on-time-sla-stated": "SLA de entrega a tiempo (%)",
  "returns-min-48h": "Devoluciones nunca en menos de 48 h",
  "volume-discount-table": "Tabla de descuentos por volumen",
  "no-carrier-negotiated-rates": "Sin tarifas de transportistas",
  "no-invented-figures": "Sin cifras inventadas",
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
  generando_secciones: "Generando las secciones de la propuesta",
  evaluando_secciones: "Evaluando las secciones (legibilidad, pertinencia, cumplimiento)",
  borradores_listos: "Borradores listos",
};

export const SERVICE_LABELS: Record<string, string> = {
  warehousing: "Almacenamiento",
  last_mile: "Última milla",
  reverse_logistics: "Devoluciones",
};

const WORKING_STATUSES = new Set(["analizando", "generando_borrador", "en_evaluación"]);

// Hay un pipeline trabajando (Parte 1 o Parte 2): la UI sigue consultando.
export function isWorking(ticket: Pick<RfpTicketSummary, "status" | "stage" | "stale">): boolean {
  return (
    WORKING_STATUSES.has(ticket.status) &&
    ticket.stage !== "error" &&
    ticket.stage !== "borradores_listos" &&
    !ticket.stale
  );
}

export function isAnalyzing(ticket: Pick<RfpTicketSummary, "status" | "stage" | "stale">): boolean {
  return ticket.status === "analizando" && ticket.stage !== "error" && !ticket.stale;
}

export function canRegenerateDrafts(ticket: Pick<RfpTicketDetail, "status" | "stage" | "stale" | "handoff">): boolean {
  const draftable = ["analisis_completo", "generando_borrador", "en_evaluación", "needs_human_review"];
  return draftable.includes(ticket.status) && Boolean(ticket.handoff?.departments?.length) && !isWorking(ticket);
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

export async function regenerateDrafts(ticketId: number): Promise<{ ticket_id: number; status: string; stage: string }> {
  return (await fetchWithAuth(`/rfp/tickets/${ticketId}/drafts`, { method: "POST" })) as {
    ticket_id: number;
    status: string;
    stage: string;
  };
}
