"""Constantes del flujo de RFPs, copiadas del BRIEFING del Hito 9 (TrackFlow).

Fuente: `content/contexts/09-agentic-workflows/trackflow-BRIEFING.es.md` §2.1, §2.3 y §5.
Los identificadores de departamento y los estados del ticket son exactamente
los del BRIEFING: las Partes 2 y 3 los reutilizan sobre el mismo ticket.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

GRAPH_NAME = "rfp_intake"
HANDOFF_CONTRACT = "trackflow.rfp_intake.handoff/v1"

# --------------------------------------------------------------------------- #
# Estados del ticket (BRIEFING §2.3). La Parte 1 solo escribe los tres primeros.
# --------------------------------------------------------------------------- #
STATUS_ANALYZING = "analizando"
STATUS_DISCARDED = "descartado"
STATUS_ANALYSIS_COMPLETE = "analisis_completo"
PART1_STATUSES = (STATUS_ANALYZING, STATUS_DISCARDED, STATUS_ANALYSIS_COMPLETE)
ALL_STATUSES = PART1_STATUSES + (
    "generando_borrador",
    "en_evaluación",
    "needs_human_review",
    "esperando_aprobación",
    "terminado",
)
# Estado al que pasará el ticket cuando la Parte 2 tome el handoff.
NEXT_STATUS = "generando_borrador"

# Etapas internas: dónde está el pipeline mientras el estado es `analizando`.
STAGE_RECEIVED = "recibido"
STAGE_CONVERTING = "convirtiendo"
STAGE_CLASSIFYING = "clasificando"
STAGE_METADATA = "extrayendo_metadatos"
STAGE_ORCHESTRATING = "orquestando"
STAGE_DEPARTMENTS = "analizando_departamentos"
STAGE_SYNTHESIZING = "sintetizando"
STAGE_DONE = "completado"
STAGE_DISCARDED = "descartado"
STAGE_ERROR = "error"

# Un ticket `analizando` sin actividad durante este tiempo se marca como `stale`
# en la API: el proceso murió a mitad del pipeline y hay que reprocesarlo.
STALE_AFTER_MINUTES = int(os.getenv("RFP_STALE_AFTER_MINUTES", "10"))


# --------------------------------------------------------------------------- #
# Departamentos (BRIEFING §2.1) y servicios que los activan
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Department:
    department_id: str
    name: str
    responsible: str
    contributes: str
    service: str  # servicio de la RFP que activa este departamento


DEPARTMENTS: dict[str, Department] = {
    "warehouse": Department(
        "warehouse",
        "Warehouse Operations",
        "Ana Whitfield",
        "Capacidad de almacenamiento, costo por pallet/SKU, tiempo de onboarding",
        "warehousing",
    ),
    "lastmile": Department(
        "lastmile",
        "Last Mile and Carrier Management",
        "Carlos Vega",
        "Costo por envío, transportistas disponibles según destino, SLA de entrega",
        "last_mile",
    ),
    "reverse": Department(
        "reverse",
        "Reverse Logistics",
        "Sofía Ramos",
        "Costo y tiempo de procesamiento de devoluciones (si el cliente lo solicita)",
        "reverse_logistics",
    ),
}
DEPARTMENT_ORDER = ("warehouse", "lastmile", "reverse")
SERVICES = ("warehousing", "last_mile", "reverse_logistics")
SERVICE_TO_DEPARTMENT = {dept.service: dept.department_id for dept in DEPARTMENTS.values()}

# Peticiones que no encajan en ningún departamento de la propuesta: las
# coordina el Director Comercial, dueño de la RFP (BRIEFING §1).
COMMERCIAL_OWNER = "Miguel Torres"

# --------------------------------------------------------------------------- #
# País → moneda (BRIEFING §5)
# --------------------------------------------------------------------------- #
COUNTRY_US = "United States"
COUNTRY_ES = "Spain"
COUNTRIES = (COUNTRY_US, COUNTRY_ES)
CURRENCY_BY_COUNTRY = {COUNTRY_US: "USD", COUNTRY_ES: "EUR"}

# --------------------------------------------------------------------------- #
# Recepción
# --------------------------------------------------------------------------- #
RAW_DIR = Path(os.getenv("RFP_RAW_DIR", str(ROOT / "data" / "raw" / "rfp")))
MAX_PDF_BYTES = int(os.getenv("RFP_MAX_PDF_BYTES", str(10 * 1024 * 1024)))
# Markdown que se manda a los agentes: las RFPs largas se truncan (y se avisa).
MAX_MARKDOWN_CHARS_FOR_LLM = int(os.getenv("RFP_MAX_MARKDOWN_CHARS", "24000"))
LLM_TIMEOUT_SECONDS = float(os.getenv("RFP_LLM_TIMEOUT_SECONDS", "45"))
# Por debajo de esta confianza, la decisión del clasificador LLM no se usa sola.
CLASSIFIER_MIN_CONFIDENCE = 0.6
