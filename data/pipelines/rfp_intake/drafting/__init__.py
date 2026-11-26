"""Generación y evaluación de respuestas a RFPs de TrackFlow (Hito 9 · Parte 2).

Arranca desde el handoff de la Parte 1 (`rfp_tickets.handoff`,
`trackflow.rfp_intake.handoff/v1`, cola `ready_for_drafting`): nunca vuelve a
leer el PDF ni el Markdown. Grafo LangGraph dedicado `rfp_drafting`:

    START → load_handoff ─Send × departamento activo─→ draft_department ─→ assemble → END

`draft_department` ejecuta, para un solo departamento, el subgrafo del ciclo
generador-evaluador `rfp_section_loop`:

    generate ─Send─→ evaluate_readability ─┐
             ├─Send─→ evaluate_relevance ──┼─→ judge ─pasa / límite─→ finalize → END
             └─Send─→ evaluate_compliance ─┘        └─falla y quedan iteraciones─→ generate

Cada departamento tiene su propio agente generador (`generators.py`) y los tres
evaluadores corren en paralelo sobre cada borrador (`evaluators.py`). Una sección
que agota `MAX_ITERATIONS` sin pasar conserva su último borrador y su
`EvaluationResult` y queda en `needs_human_review`: nunca se descarta.
Diseño completo: `docs/rfp-drafting/rfp-drafting-design.md`.
"""
