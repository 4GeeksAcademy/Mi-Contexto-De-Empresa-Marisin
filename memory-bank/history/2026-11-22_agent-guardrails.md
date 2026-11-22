# Plan y registro — Aseguramiento de Agentes: Harness y Guardrails · Parte 2 (TrackFlow)

> **Proyecto 4Geeks:** "Hito 8 — Aseguramiento de Agentes: Harness y Guardrails (Parte 2 de 2)". **Ticket #SEC-114.**
> **Rama:** `feature/agent-guardrails`, creada por Marisin **desde `feature/agent-memory`** (PR #32 pendiente de merge): mismo agente.
> **Dependencias:** ninguna nueva. El parche no toca `pyproject.toml` ni `uv.lock`.
> **BRIEFING:** `content/contexts/08-agent-engineering/harnessing/trackflow-BRIEFING.es.md` (resumido en `docs/agent-guardrails/guardrails-design.md` §1 y §5).

## 0. Reglas
1. Un commit por acción, prefijo convencional y descripción en español.
2. El agente asegurado es el de CX de Valentina Cruz: el mismo grafo LangGraph + MCP + memoria.
3. Más de un guardrail: una capa por tipo de fallo (estructural, contenido, seguridad).
4. Tests deterministas como criterio de aceptación; el modelo vivo es solo un smoke check.
5. Las consultas de dominio siguen la ruta anterior: los evals grabados no se regraban.
6. No se edita ningún `.env*`.

## 1. Rúbrica → dónde se cumple

| Criterio | Dónde |
|---|---|
| Mismo agente de empresa (identidad, tools, dominio KB) | `harness/prompts.py` (CX de Valentina Cruz), mismo grafo; design §1 |
| Redirige fuera de dominio en vez de responder como asistente genérico | `small_talk` + `responses.REDIRECT`; tests `test_small_talk_*`, `test_general_logistics_*` |
| Rechaza ≥3 variantes de cambio de instrucciones (documentadas en el PR) | 7 en la batería viva + 23 en tests + 3 × 5 reformulaciones; design §4 |
| Rechaza uso personal sin dejar de ser útil | `personal_task` + `test_personal_tasks_are_refused_and_domain_questions_still_work` |
| Más de un guardrail | 6 capas (design §2) |
| Contenido de tools/RAG nunca es instrucción (caso de prueba) | `harness/isolation.py`; `test_an_instruction_inside_a_rag_document_is_isolated_and_an_obedient_model_is_caught` |
| Tests deterministas del harness | `tests/pipelines/test_agent_guardrails_{input,output,graph}.py` + `tests/test_agent_routes.py`, en CI |
| Cada bloqueo/redirección registrado con su tipo de fallo | `harness/events.py`; `GET /agent/guardrails/summary`; `scripts/agent_guardrails_report.py` |
| Respeta nombres, temas y restricciones del BRIEFING | dominio por país, §3 del BRIEFING en prompt, guardia de entrada y de salida; 4 casos obligatorios (design §5) |

## 2. Decisiones (D1–D10)

| # | Decisión | Por qué |
|---|---|---|
| D1 | Prompt propio del agente de CX (antes usaba el del RAG comercial). | El BRIEFING pide blindar el agente de CX; un prompt genérico o ajeno no se acepta. |
| D2 | Guardia de entrada determinista dentro de `receive_question`; bloqueo en nodo propio `guardrail_block` (plantilla, sin LLM ni tools). | Las rutas de dominio no cambian; lo bloqueado nunca toca el modelo. |
| D3 | Segunda capa = campo `scope` en la salida estructurada del enrutador. | Paráfrasis que las reglas no conocen, sin llamada extra. |
| D4 | Directorio de envíos de demostración `data/agent/shipments.json` con dueños. | No hay API de tracking; el caso 3 exige rechazar por autorización. |
| D5 | Pedido ajeno e inexistente → misma respuesta. | Evita enumerar pedidos cambiando dígitos. |
| D6 | `country_lock` para la mezcla de políticas: búsqueda orientada al país real, filtro de chunks y país fijado por el sistema en el prompt. | BRIEFING caso 4: nunca mezclar EE. UU. y España. |
| D7 | Aislamiento: sanitizar + delimitar + jerarquía; también en los campos de las tools. | Inyección indirecta. |
| D8 | Guardia de salida sobre la respuesta compuesta, con canario. | Última barrera para fugas y datos sensibles. |
| D9 | Eventos en log + Redis Stream + trace; resumen por endpoint y comando. | Observabilidad mínima del enunciado. |
| D10 | Un mensaje bloqueado descarta la propuesta de memoria pendiente. | Nunca se aprueba memoria con un mensaje abusivo. |

## 3. Commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan del harness y los guardrails del agente` |
| 2 | Normalización y eventos | `feat: añade la normalización de texto y el registro de eventos de guardrails` |
| 3 | Directorio de envíos + autorización | `feat: añade la autorización por sesión con el directorio de envíos de demostración` |
| 4 | Guardia de entrada | `feat: añade la guardia de entrada determinista del agente` |
| 5 | Aislamiento + prompt seguro + generación | `feat: añade el system prompt seguro de CX y el aislamiento del contenido externo` |
| 6 | Guardia de salida + respuestas | `feat: añade la guardia de salida y las respuestas de rechazo y reconducción` |
| 7 | Enrutador (`scope` + eventos estructurales) | `feat: añade la clasificación de alcance a la salida estructurada del enrutador` |
| 8 | Grafo, nodos, estado, trace, runner | `feat: integra el harness en el grafo del agente` |
| 9 | API | `feat: expone el veredicto del harness y el resumen de guardrails en la API` |
| 10 | conftest | `test: aísla el registro de guardrails y la generación en los tests` |
| 11 | Tests de entrada | `test: añade las pruebas deterministas de la guardia de entrada` |
| 12 | Tests de salida y aislamiento | `test: añade las pruebas de la guardia de salida y del aislamiento` |
| 13 | Tests del grafo + adaptación de los existentes | `test: añade las pruebas del harness por el grafo y adapta las existentes` |
| 14 | Batería + scripts | `feat: añade la batería de abuso y los scripts de evidencia y resumen de guardrails` |
| 15 | Diseño | `docs: documenta el harness y los guardrails del agente` |
| 16 | `scripts/README*.md` | `docs: documenta los scripts de guardrails` |
| 17 | CI | `ci: ejecuta las pruebas del harness del agente` |
| 18 | `progress.md` | `docs: registra el harness del agente en progress` |

## 4. Verificación (Marisin, en el Codespace)

| # | Paso | Criterio |
|---|---|---|
| V1 | `python -m pytest -q` | Todo en verde. |
| V2 | `python -m pytest -q tests/pipelines/test_agent_guardrails_input.py tests/pipelines/test_agent_guardrails_output.py tests/pipelines/test_agent_guardrails_graph.py` | Capturas de los tests deterministas. |
| V3 | `docker compose up -d redis qdrant` + `python scripts/agent_guardrails_evidence.py` | 20/20 casos OK; `docs/agent-guardrails/evidence/`. |
| V4 | `python scripts/agent_guardrails_report.py --since <inicio>` | Resumen por tipo de fallo. |

## 5. Registro

* 2026-11-22 — Plan e implementación preparados por Claude en un parche (`agent-guardrails.patch`). Probados en el entorno de Claude: guardias, aislamiento y salida (105 tests) con Python puro; grafo, enrutador, memoria y evals con un doble local de LangGraph (sin FastAPI ni Redis). Pendiente de Marisin: V1–V4.
