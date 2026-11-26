"""Aprobación humana y cierre del documento de las RFPs de TrackFlow (Hito 9 · Parte 3).

Arranca desde el handoff de la Parte 2 (`rfp_tickets.drafting_handoff`,
`trackflow.rfp_drafting.handoff/v1`, cola `ready_for_approval`) sobre el mismo
ticket. Dos grafos LangGraph con checkpointer (SQLite):

- `rfp_department_approval`, un hilo por departamento activo
  (`rfp-{ticket_id}:{department_id}`): se detiene en `human_approval` con
  `interrupt()` hasta que su responsable (Ana Whitfield, Carlos Vega o Sofía
  Ramos) aprueba, rechaza o pide cambios; pedir cambios vuelve al generador de la
  Parte 2 de ese departamento, con límite de rondas.
- `rfp_approval`, el hilo del ticket (`rfp-{ticket_id}`): detecta los triggers
  de conflicto del BRIEFING §7, arbitra con el árbitro fijo (reglas, nunca un LLM),
  espera los sign-offs y, con todas las secciones aprobadas, genera el documento final.

Estados del ticket: `esperando_aprobación` mientras haya una aprobación
pendiente y `terminado` con el documento final guardado. Cada nodo deja su traza
(agente, input, output, timestamp) en el estado y en `rfp_trace_events`.
Diseño completo: `docs/rfp-approval/rfp-approval-design.md`.
"""
