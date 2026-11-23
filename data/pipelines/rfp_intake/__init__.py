"""Recepción y enrutamiento de RFPs de TrackFlow (Hito 9 · Parte 1).

Grafo LangGraph dedicado `rfp_intake`, separado del grafo del agente de CX
(`services/agent/`):

    convert_document → classify_document ─rechazada─→ discard_document → END
                                           └aceptada──→ extract_metadata → orchestrate
    orchestrate ─Send × departamento activo─→ department_worker ─┐
                └sin departamentos──────────────────────────────┤
                                                    synthesize ←┘ → END

Los routers de `services/rfp/` solo crean el ticket y disparan `runner.process_ticket`
en segundo plano; el grafo, los agentes y la persistencia viven aquí.
Diseño completo: `docs/rfp-intake/rfp-intake-design.md`.
"""
