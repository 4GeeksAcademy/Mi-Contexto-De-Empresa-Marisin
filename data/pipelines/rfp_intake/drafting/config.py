"""Constantes de la Parte 2: estados, etapas, límites y reglas de cumplimiento.

Los estados del ticket son exactamente los del BRIEFING (§2.3) para la Parte 2;
los de la Parte 3 (`esperando_aprobación`, `terminado`) no se escriben aquí.
Las reglas de cumplimiento copian el BRIEFING §5 (y la regla «nunca inventes»
de §2.3) con un identificador estable para `EvaluationResult.compliance.rule_ids`.
"""

from __future__ import annotations

import os

from ..config import HANDOFF_CONTRACT, STATUS_ANALYSIS_COMPLETE

GRAPH_NAME = "rfp_drafting"
SECTION_GRAPH_NAME = "rfp_section_loop"
INPUT_CONTRACT = HANDOFF_CONTRACT  # trackflow.rfp_intake.handoff/v1 (Parte 1)
OUTPUT_CONTRACT = "trackflow.rfp_drafting.handoff/v1"  # lo que recibe la Parte 3

# --------------------------------------------------------------------------- #
# Estados del ticket que escribe la Parte 2 (BRIEFING §2.3)
# --------------------------------------------------------------------------- #
STATUS_GENERATING = "generando_borrador"
STATUS_EVALUATING = "en_evaluación"
STATUS_NEEDS_REVIEW = "needs_human_review"
PART2_STATUSES = (STATUS_GENERATING, STATUS_EVALUATING, STATUS_NEEDS_REVIEW)
# Estado que la Parte 3 escribirá al tomar el handoff (solo se nombra, no se escribe).
NEXT_STATUS = "esperando_aprobación"
# Desde dónde se puede (re)generar: el handoff de la Parte 1, un estado de la Parte 2 o,
# de forma explícita, un ticket de la Parte 3 que espera aprobación (p. ej. con una
# sección rechazada: un rechazo pide una nueva ejecución de los borradores).
DRAFTABLE_STATUSES = (STATUS_ANALYSIS_COMPLETE, *PART2_STATUSES, NEXT_STATUS)

# Etapas internas del ticket durante la Parte 2 (columna `stage`).
STAGE_GENERATING = "generando_secciones"
STAGE_EVALUATING = "evaluando_secciones"
STAGE_DRAFTS_READY = "borradores_listos"
PART2_STAGES = (STAGE_GENERATING, STAGE_EVALUATING, STAGE_DRAFTS_READY)

# Estado de cada sección (`rfp_department_sections.draft_status`).
SECTION_GENERATING = "generando_borrador"
SECTION_EVALUATING = "en_evaluación"
SECTION_PASSED = "evaluacion_superada"
SECTION_NEEDS_REVIEW = "needs_human_review"
SECTION_STATUSES = (SECTION_GENERATING, SECTION_EVALUATING, SECTION_PASSED, SECTION_NEEDS_REVIEW)

# --------------------------------------------------------------------------- #
# Ciclo generador-evaluador
# --------------------------------------------------------------------------- #
# KPI del BRIEFING §3: menos de 2 iteraciones de media por sección. Con 3 hay
# margen para dos correcciones antes de pedir revisión humana.
MAX_ITERATIONS = max(1, int(os.getenv("RFP_DRAFT_MAX_ITERATIONS", "3")))
# Encadenar la Parte 2 al terminar la Parte 1 (en el mismo proceso, en segundo plano).
AUTO_DRAFT = os.getenv("RFP_AUTO_DRAFT", "1").strip().lower() not in {"0", "false", "no"}
# Base de conocimiento del generador: "files" (documentos de docs/company-knowledge-base/)
# o "semantic" (búsqueda en Qdrant con el RAG del Hito 7; si falla, vuelve a "files").
KNOWLEDGE_MODE = os.getenv("RFP_DRAFT_KNOWLEDGE", "files").strip().lower()

# --------------------------------------------------------------------------- #
# Umbrales del evaluador de legibilidad (sobre la prosa, sin tablas)
# --------------------------------------------------------------------------- #
# Fernández Huerta (español): 60-70 normal, 50-60 algo difícil, 30-50 difícil.
# Una propuesta económica es texto técnico; por debajo de 40 ya cuesta leerla.
MIN_FERNANDEZ_HUERTA = 40.0
# Inglés (si el generador respondiera en inglés): Flesch-Kincaid como en la Parte 1.
MAX_FLESCH_KINCAID_GRADE = 14.0
MAX_AVG_WORDS_PER_SENTENCE = 25.0
MIN_SECTION_WORDS = 60
MAX_SECTION_WORDS = 900

# --------------------------------------------------------------------------- #
# Reglas de cumplimiento (BRIEFING §5 + §2.3)
# --------------------------------------------------------------------------- #
RULE_CURRENCY = "currency-by-country"
RULE_SLA = "on-time-sla-stated"
RULE_RETURNS_48H = "returns-min-48h"
RULE_DISCOUNT_TABLE = "volume-discount-table"
RULE_CARRIER_RATES = "no-carrier-negotiated-rates"
RULE_NO_INVENTED_FIGURES = "no-invented-figures"

COMPLIANCE_RULES: dict[str, str] = {
    RULE_CURRENCY: "El precio se cotiza en USD para Estados Unidos y en EUR para España (según client_country).",
    RULE_SLA: "Toda propuesta indica el SLA de entrega a tiempo (%) que TrackFlow se compromete a cumplir.",
    RULE_RETURNS_48H: "Ninguna propuesta promete procesar devoluciones en menos de 48 horas.",
    RULE_DISCOUNT_TABLE: "Toda propuesta incluye una tabla de descuentos por volumen.",
    RULE_CARRIER_RATES: "Ninguna propuesta revela tarifas negociadas con transportistas: solo el costo final al cliente.",
    RULE_NO_INVENTED_FIGURES: "Ninguna cifra que no esté en la RFP, en el tarifario de referencia o en la base de conocimiento.",
}
COMPLIANCE_RULE_SOURCE = {
    RULE_CURRENCY: "BRIEFING §5",
    RULE_SLA: "BRIEFING §5",
    RULE_RETURNS_48H: "BRIEFING §5",
    RULE_DISCOUNT_TABLE: "BRIEFING §5",
    RULE_CARRIER_RATES: "BRIEFING §5",
    RULE_NO_INVENTED_FIGURES: "BRIEFING §2.3",
}
MIN_RETURNS_HOURS = 48
# Transportistas con los que TrackFlow trabaja (CONTEXT / base de conocimiento).
CARRIERS = ("ups", "fedex", "dhl", "mrw", "seur")
