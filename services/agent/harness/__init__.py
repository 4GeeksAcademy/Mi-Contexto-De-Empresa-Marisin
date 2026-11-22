"""Harness de protección del agente de CX de TrackFlow (Hito 8 · Parte 2, Ticket #SEC-114).

El modelo decide; el harness ejecuta, controla y contiene. Cada tipo de fallo
tiene su propia capa (ver `docs/agent-guardrails/guardrails-design.md`):

| Capa | Módulo | Fallo que cubre |
|---|---|---|
| Guardia de entrada determinista (inyección, uso personal, small talk, datos sensibles, mezcla de políticas) | `input_guard.py` | seguridad / contenido |
| Autorización por sesión (pedidos/tracking de otra persona) | `authorization.py` | contenido (BRIEFING caso 3) |
| Clasificación semántica del alcance en la salida estructurada del enrutador (`scope`) | `services/agent/routing.py` | seguridad / contenido |
| System prompt con jerarquía de instrucciones y canario | `prompts.py` | seguridad |
| Aislamiento de texto externo (chunks RAG, datos de tools) | `isolation.py` | seguridad (inyección indirecta) |
| Validación de la salida (formato, fugas del prompt, datos sensibles) | `output_guard.py` | estructural / contenido / seguridad |
| Observabilidad (cada bloqueo o redirección con su tipo de fallo) | `events.py` | — |

Las capas deterministas no dependen de un LLM: los tests las ejercitan con
fixtures fijos y el CI falla si una entrada abusiva pasara como permitida.
"""
