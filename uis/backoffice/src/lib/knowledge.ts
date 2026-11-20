import { fetchWithAuth } from "./api";

// Contrato de POST /knowledge/query (Hito 7 — RAG y Base de Conocimiento).
// La API solo devuelve el texto generado por el modelo: ni chunks ni puntuaciones.
export interface KnowledgeQueryResponse {
  answer: string;
}

export const QUESTION_MAX_LENGTH = 500;

// Preguntas típicas de las marcas, sacadas del BRIEFING de TrackFlow.
export const EXAMPLE_QUESTIONS = [
  "¿Cuál es la ventana de devolución estándar?",
  "¿Qué transportista cubre mejor Aragón rural?",
  "¿Podemos garantizar el SLA de entrega durante el Black Friday?",
  "¿Podemos ofrecer un descuento de almacenamiento a una marca con 60 m³ al mes?",
];

export async function askKnowledgeBase(question: string): Promise<string> {
  const data = (await fetchWithAuth("/knowledge/query", {
    method: "POST",
    body: JSON.stringify({ question }),
  })) as Partial<KnowledgeQueryResponse>;
  if (typeof data.answer !== "string" || !data.answer.trim()) {
    throw new Error("El asistente no ha devuelto ninguna respuesta. Inténtalo de nuevo.");
  }
  return data.answer;
}
