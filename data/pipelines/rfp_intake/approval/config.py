"""Constantes de la Parte 3: estados, aprobación humana, arbitraje, checkpointer y límites.

Fuente: BRIEFING del Hito 9 (`trackflow-BRIEFING.es.md`):

- §2.3: estados `esperando_aprobación` (pausa humana por departamento) y
  `terminado` (documento final generado); `DepartmentSection.approval_status`,
  `approver` y `approved_at`; `FinalDocument` = `ticket_id`, `sections`,
  `currency`, `generated_at`.
- §6: cada responsable nombrado aprueba **su** sección de forma independiente,
  sin bloquear a los demás; el documento final solo con todas las secciones
  activas aprobadas; sin escalera jerárquica (responsables pares).
- §7: triggers de conflicto con árbitro fijo y regla de resolución
  (`volume-vs-capacity`, `returns-sla-breach`, `currency-mismatch`). Los agentes
  solo señalan el conflicto: nunca lo resuelven por consenso.
- §3: KPI de tiempo de aprobación por departamento y tiempo de armado de la propuesta.
"""

from __future__ import annotations

import os
from pathlib import Path

from .. import config as intake_config
from ..drafting import config as drafting_config

GRAPH_NAME = "rfp_approval"  # grafo del ticket: arbitraje, espera de sign-offs y cierre
DEPARTMENT_GRAPH_NAME = "rfp_department_approval"  # rama de un departamento: HITL + revisión
INPUT_CONTRACT = drafting_config.OUTPUT_CONTRACT  # trackflow.rfp_drafting.handoff/v1 (Parte 2)
DOCUMENT_CONTRACT = "trackflow.rfp_final_document/v1"

# --------------------------------------------------------------------------- #
# Estados del ticket que escribe la Parte 3 (BRIEFING §2.3)
# --------------------------------------------------------------------------- #
STATUS_AWAITING = "esperando_aprobación"
STATUS_DONE = "terminado"
PART3_STATUSES = (STATUS_AWAITING, STATUS_DONE)
# La Parte 3 toma los tickets que la Parte 2 dejó con borradores listos.
APPROVABLE_STATUSES = (drafting_config.STATUS_EVALUATING, drafting_config.STATUS_NEEDS_REVIEW)

# Etapas internas (columna `stage`) mientras el estado es `esperando_aprobación` / `terminado`.
STAGE_AWAITING = "esperando_aprobaciones"
STAGE_ARBITRATING = "arbitrando"
STAGE_REVISING = "revisando_secciones"
STAGE_CLOSING = "generando_documento"
STAGE_REJECTED = "seccion_rechazada"
STAGE_DONE = "documento_final"
PART3_STAGES = (STAGE_AWAITING, STAGE_ARBITRATING, STAGE_REVISING, STAGE_CLOSING, STAGE_REJECTED, STAGE_DONE)

# --------------------------------------------------------------------------- #
# Aprobación humana por departamento
# --------------------------------------------------------------------------- #
# Lo que puede responder el responsable (enunciado: aprobar, rechazar o solicitar cambios).
DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"
DECISION_CHANGES = "request_changes"
DECISIONS = (DECISION_APPROVE, DECISION_REJECT, DECISION_CHANGES)

# `rfp_department_sections.approval_status`.
APPROVAL_PENDING = "pendiente"  # la rama está interrumpida esperando al responsable
APPROVAL_CHANGES = "cambios_solicitados"  # se está reescribiendo (pidió cambios el humano o el árbitro)
APPROVAL_APPROVED = "aprobada"
APPROVAL_REJECTED = "rechazada"
APPROVAL_STATUSES = (APPROVAL_PENDING, APPROVAL_CHANGES, APPROVAL_APPROVED, APPROVAL_REJECTED)

MIN_COMMENT_CHARS = 10  # rechazar o pedir cambios exige decir por qué
MAX_COMMENT_CHARS = 2000

# Límite de rondas de revisión por departamento (cambios pedidos por el responsable o
# forzados por el árbitro). Al pedir cambios con el límite agotado, la sección queda
# rechazada: el bucle humano ↔ generador nunca es infinito.
MAX_APPROVAL_ROUNDS = max(1, int(os.getenv("RFP_APPROVAL_MAX_ROUNDS", "3")))

# --------------------------------------------------------------------------- #
# Arbitraje (BRIEFING §7)
# --------------------------------------------------------------------------- #
TRIGGER_VOLUME_CAPACITY = "volume-vs-capacity"
TRIGGER_RETURNS_SLA = "returns-sla-breach"
TRIGGER_CURRENCY = "currency-mismatch"
TRIGGERS = (TRIGGER_VOLUME_CAPACITY, TRIGGER_RETURNS_SLA, TRIGGER_CURRENCY)

COMMERCIAL_DIRECTOR = intake_config.COMMERCIAL_OWNER  # Miguel Torres (Director Comercial)
REVERSE_OWNER = intake_config.DEPARTMENTS["reverse"].responsible  # Sofía Ramos

# Árbitro fijo y regla de cada trigger (copiados del BRIEFING §7).
ARBITERS = {
    TRIGGER_VOLUME_CAPACITY: COMMERCIAL_DIRECTOR,
    # Sofía Ramos rechaza su propia sección; si la promesa está en otra sección, decide Miguel Torres.
    TRIGGER_RETURNS_SLA: REVERSE_OWNER,
    TRIGGER_CURRENCY: COMMERCIAL_DIRECTOR,
}
RESOLUTION_RULES = {
    TRIGGER_VOLUME_CAPACITY: "Limitar el volumen a la capacidad de warehouse; lastmile revisa volumen y costo a la baja.",
    TRIGGER_RETURNS_SLA: "Forzar request_changes en la sección que promete devoluciones en menos de 48 h; "
                         "sin documento final hasta que cumpla.",
    TRIGGER_CURRENCY: "Reescribir las secciones ofensoras a la moneda del país (US→USD, Spain→EUR); "
                      "rechazar si no se resuelve tras el límite de iteraciones.",
}
# Rondas de arbitraje por ticket: cada ronda reabre las secciones ofensoras. Agotadas,
# las secciones que siguen en conflicto quedan rechazadas (no hay documento final).
MAX_ARBITRATION_ROUNDS = max(1, int(os.getenv("RFP_ARBITRATION_MAX_ROUNDS", "2")))

# Capacidad mensual de preparación de pedidos de cada almacén (pedidos/mes) para el
# trigger `volume-vs-capacity`. El BRIEFING no la da: como el tarifario de la Parte 2,
# es la capacidad de referencia del proyecto (Ana Whitfield) y se puede ajustar por entorno.
WAREHOUSE_MONTHLY_CAPACITY = {
    "USD": int(os.getenv("RFP_CAPACITY_LOS_ANGELES", "20000")),  # Los Ángeles
    "EUR": int(os.getenv("RFP_CAPACITY_ZARAGOZA", "15000")),  # Zaragoza
}

# Abrir la aprobación sola al terminar la Parte 2 (tercera tarea de fondo, en orden).
AUTO_APPROVAL = os.getenv("RFP_AUTO_APPROVAL", "1").strip().lower() not in {"0", "false", "no"}

# --------------------------------------------------------------------------- #
# Checkpointer e identidad de los hilos
# --------------------------------------------------------------------------- #
# "sqlite" (por defecto; `langgraph-checkpoint-sqlite`) o "memory" (solo desarrollo y tests).
CHECKPOINTER = os.getenv("RFP_CHECKPOINTER", "sqlite").strip().lower()
CHECKPOINT_PATH = Path(
    os.getenv("RFP_CHECKPOINT_PATH", str(intake_config.ROOT / "data" / "checkpoints" / "rfp_approval.sqlite"))
)
RECURSION_LIMIT = 50


def ticket_thread_id(ticket_id: int) -> str:
    """Hilo del grafo del ticket: un checkpoint por ticket, nunca compartido."""
    return f"rfp-{ticket_id}"


def department_thread_id(ticket_id: int, department_id: str) -> str:
    """Hilo de la rama de un departamento: se pausa y se reanuda sin tocar a las demás."""
    return f"rfp-{ticket_id}:{department_id}"
