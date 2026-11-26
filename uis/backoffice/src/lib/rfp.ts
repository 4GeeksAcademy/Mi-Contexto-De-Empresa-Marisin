import { fetchWithAuth } from "./api";

// Contrato de /rfp/tickets (Hito 9 · Partes 1-3 — recepción, borradores y aprobación).
// El POST responde 202 al momento; el pipeline corre en segundo plano y la UI
// consulta el estado con GET mientras haya trabajo en curso (análisis, borradores o
// aprobaciones pendientes). Cada responsable registra su decisión en su sección.

export type RfpStatus =
  | "analizando"
  | "descartado"
  | "analisis_completo"
  | "generando_borrador"
  | "en_evaluación"
  | "needs_human_review"
  | "esperando_aprobación"
  | "terminado"
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
  // Parte 3: aprobación humana de la sección (BRIEFING §2.3).
  approval_status?: ApprovalStatus | null;
  approver?: string | null;
  approved_at?: string | null;
  approval_round?: number;
  approval_comment?: string | null;
  approval_requested_at?: string | null;
  approval_history?: Record<string, unknown>[];
}

export type ApprovalStatus = "pendiente" | "cambios_solicitados" | "aprobada" | "rechazada";
export type ApprovalDecision = "approve" | "reject" | "request_changes";

// Payload del interrupt() de una rama: lo mínimo para decidir sin releer todo.
export interface ApprovalRequest {
  ticket_id: number;
  department_id: string;
  department_name: string;
  responsible: string;
  round: number;
  max_rounds: number;
  client_name: string | null;
  currency: string | null;
  draft_status: string | null;
  provisional: boolean;
  iterations: number;
  overall_pass: boolean | null;
  violations: string[];
  missing_aspects: string[];
  arbitration_notes: string[];
  last_comment: string | null;
  allowed_decisions: ApprovalDecision[];
}

export interface TraceEvent {
  id: number;
  graph: string;
  thread_id: string | null;
  department_id: string | null;
  node: string;
  agent: string;
  status: "ok" | "interrupted" | "error";
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  started_at: string | null;
  finished_at: string;
  duration_ms: number | null;
}

export interface FinalDocumentSection {
  department_id: string;
  department_name: string;
  responsible: string;
  approver: string;
  approved_at: string;
  approval_rounds: number;
  approval_minutes: number | null;
}

export interface FinalDocument {
  contract: string;
  ticket_id: number;
  client_name: string | null;
  currency: string | null;
  sections: FinalDocumentSection[];
  arbitrations: { round: number; trigger: string; arbiter: string; action: string; departments: string[]; detail: string }[];
  metrics: Record<string, unknown>;
  delivered_to: string;
  markdown: string;
  generated_at: string;
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
  // Parte 3: "approval" en las iteraciones de una reescritura pedida durante la aprobación.
  phase?: string;
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
  approval_requests?: ApprovalRequest[];
  final_document_available?: boolean;
  error_message: string | null;
}

export const STATUS_LABELS: Record<string, string> = {
  analizando: "Analizando",
  descartado: "Descartado",
  analisis_completo: "Análisis completo",
  generando_borrador: "Generando borrador",
  "en_evaluación": "En evaluación",
  needs_human_review: "Revisión humana",
  "esperando_aprobación": "Esperando aprobación",
  terminado: "Terminado",
};

export const APPROVAL_STATUS_LABELS: Record<string, string> = {
  pendiente: "Pendiente de aprobación",
  cambios_solicitados: "Reescribiendo (cambios pedidos)",
  aprobada: "Aprobada",
  rechazada: "Rechazada",
};

export const DECISION_LABELS: Record<ApprovalDecision, string> = {
  approve: "Aprobar",
  request_changes: "Pedir cambios",
  reject: "Rechazar",
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
  esperando_aprobaciones: "Esperando el visto bueno de cada responsable",
  arbitrando: "Arbitrando un conflicto entre secciones",
  revisando_secciones: "Reescribiendo secciones con los cambios pedidos",
  generando_documento: "Generando el documento final",
  seccion_rechazada: "Sección rechazada: hay que regenerar los borradores",
  documento_final: "Documento final generado",
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

// Aprobaciones en curso: una rama se está reescribiendo o el ticket está cerrando/arbitrando.
export function isApprovalBusy(ticket: Pick<RfpTicketDetail, "status" | "stage" | "sections">): boolean {
  return (
    ticket.status === "esperando_aprobación" &&
    ticket.stage !== "seccion_rechazada" &&
    ticket.stage !== "error" &&
    (["arbitrando", "revisando_secciones", "generando_documento"].includes(ticket.stage) ||
      ticket.sections.some((section) => section.approval_status === "cambios_solicitados"))
  );
}

export function canStartApproval(ticket: Pick<RfpTicketDetail, "status" | "stage" | "drafting_handoff">): boolean {
  const ready = ["en_evaluación", "needs_human_review"].includes(ticket.status) && ticket.stage === "borradores_listos";
  const restart = ticket.status === "esperando_aprobación" && ["seccion_rechazada", "error"].includes(ticket.stage);
  return Boolean(ticket.drafting_handoff) && (ready || restart);
}

export function canRegenerateDrafts(ticket: Pick<RfpTicketDetail, "status" | "stage" | "stale" | "handoff">): boolean {
  const draftable = ["analisis_completo", "generando_borrador", "en_evaluación", "needs_human_review", "esperando_aprobación"];
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

export async function startApproval(ticketId: number): Promise<{ ticket_id: number; status: string; stage: string }> {
  return (await fetchWithAuth(`/rfp/tickets/${ticketId}/approvals`, { method: "POST" })) as {
    ticket_id: number;
    status: string;
    stage: string;
  };
}

export interface ApprovalAccepted {
  ticket_id: number;
  department_id: string;
  decision: ApprovalDecision;
  approval_status: ApprovalStatus | null;
  status: string;
  stage: string;
  resumed: boolean;
}

export async function submitApproval(
  ticketId: number,
  departmentId: string,
  body: { decision: ApprovalDecision; approver: string; comment: string },
): Promise<ApprovalAccepted> {
  return (await fetchWithAuth(`/rfp/tickets/${ticketId}/approvals/${departmentId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })) as ApprovalAccepted;
}

export async function getRfpTrace(ticketId: number): Promise<TraceEvent[]> {
  const data = (await fetchWithAuth(`/rfp/tickets/${ticketId}/trace`)) as { events?: TraceEvent[] };
  return Array.isArray(data.events) ? data.events : [];
}

export async function getFinalDocument(ticketId: number): Promise<FinalDocument> {
  return (await fetchWithAuth(`/rfp/tickets/${ticketId}/document`)) as FinalDocument;
}
