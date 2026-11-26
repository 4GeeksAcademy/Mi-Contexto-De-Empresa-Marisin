# Plan y registro — Flujo Agéntico de RFPs: Aprobación y Cierre · Parte 3 de 3 (TrackFlow)

> **Proyecto 4Geeks:** "Hito — Flujo Agéntico de RFPs: Aprobación y Cierre (Parte 3 de 3)".
> **Rama:** `feature/rfp-approval-completion`, creada **desde `feature/rfp-response-generation`** (PR #35 sin mergear; encadena sobre #34 y #29–#33).
> **Dependencia nueva:** `langgraph-checkpoint-sqlite` (la añade Marisin con `uv add`; el parche no toca `pyproject.toml` ni `uv.lock`).
> **BRIEFING:** `content/contexts/09-agentic-workflows/trackflow-BRIEFING.es.md` (§2.1 responsables, §2.3 estados y entidades, §3 KPIs, §6 aprobación, §7 conflictos y árbitro).

## 0. Reglas
1. Un commit por acción, prefijo convencional y descripción en español.
2. Partir del handoff de la Parte 2 (`rfp_tickets.drafting_handoff` + `ready_for_approval`) sobre el mismo ticket: ni el PDF ni el Markdown.
3. Sin API nuevo: rutas en `services/rfp/router.py`; grafos en `data/pipelines/rfp_intake/approval/`; CLI en `scripts/`.
4. Aprobaciones, documento final y traza en PostgreSQL (Supabase); el estado de los grafos en el checkpointer SQLite. Nunca TinyDB ni JSON.
5. Estados exactamente los del BRIEFING: `esperando_aprobación` y `terminado`; el resto son etapas (`stage`).
6. Sin escalera jerárquica: aprueba el responsable nombrado de cada departamento activo.
7. Sin `.env*`: las variables nuevas (`RFP_CHECKPOINTER`, `RFP_CHECKPOINT_PATH`, `RFP_APPROVAL_MAX_ROUNDS`, `RFP_ARBITRATION_MAX_ROUNDS`, `RFP_AUTO_APPROVAL`, `RFP_CAPACITY_*`) tienen valor por defecto.

## 1. Rúbrica → dónde se cumple

| Criterio | Dónde |
|---|---|
| Pausa antes de la aprobación de cada departamento y persiste su estado | `approval/graph.py` `human_approval` con `interrupt(ApprovalRequest)`; `checkpoint.py` (`SqliteSaver`) |
| La pausa afecta solo a esa rama (B aprobada con A interrumpida) | un hilo por rama `rfp-{ticket}:{dept}`; `test_approving_B_while_A_is_still_interrupted` (estado + traza); escenario E2E `parallel` |
| Reanuda en el punto de interrupción, sin reiniciar | `ApprovalService.decide/resume` → `Command(resume=…)`; `test_resume_continues_at_the_interrupted_node_without_restarting` |
| `thread_id` namespaced por ticket y departamento | `config.ticket_thread_id` / `department_thread_id`; `test_concurrent_tickets_do_not_share_checkpoints` |
| Límite de iteraciones aplicado y verificable | `MAX_APPROVAL_ROUNDS` (3) en `route_after_human`/`route_after_prepare`; `MAX_ARBITRATION_ROUNDS` (2) en `arbiter.arbitrate`; tests y escenario `limit` |
| Arbitraje con los triggers y el árbitro fijo del BRIEFING | `approval/conflicts.py` (estructurado) + `approval/arbiter.py` (`mode = "rule"`) |
| Traza: agente, input, output y timestamp por nodo | `approval/trace.py` (estado + `rfp_trace_events`); Partes 1 y 2 desde sus runners; `GET /rfp/tickets/{id}/trace` |
| Documento final automático solo con todo aprobado | `close_document` tras `await_signoffs` y `detect_conflicts`; `approval/document.py` |
| `esperando_aprobación` / `terminado` | `claim_for_approval`, `save_final_document` |
| Ruta E2E reproducible con aprobaciones simuladas | `approval/e2e.py` + `scripts/rfp_approval_run.py --e2e` + `tests/pipelines/test_rfp_approval_e2e.py` |
| Partes 1 → 3 sin saltos | encadenado en las tareas de fondo del `POST`; `test_the_three_parts_chain_and_each_responsible_approves_independently` |
| Validar la respuesta humana antes del resume | `schemas.ApprovalDecision` + `ApprovalService.submit` (422/409); `test_an_invalid_decision_never_reaches_the_graph` |
| UI de aprobación en `uis/backoffice` | `src/app/rfp/page.tsx` (`ApprovalBox`, `ApprovalPanel`) + `src/lib/rfp.ts` |

## 2. Decisiones (D1–D12)

| # | Decisión | Por qué |
|---|---|---|
| D1 | Base `feature/rfp-response-generation` (PR encadenado). | El PR #35 no está en `main`. |
| D2 | Dos grafos: `rfp_department_approval` (un hilo por rama) y `rfp_approval` (hilo del ticket). | Con `interrupt` en ramas `Send` del mismo superstep, una rama que pide cambios no podría reescribirse hasta que respondieran las demás. El enunciado admite checkpointear ramas por separado. |
| D3 | Las ramas se lanzan en hilos propios (`ThreadPoolExecutor`). | Cada rama es una ejecución de primer nivel con su `thread_id`: su `interrupt` no se propaga al grafo del ticket. |
| D4 | El ticket espera los sign-offs con un `interrupt` en bucle (`await_signoffs`) y se reanuda con el `SignoffEvent` de cada rama. | Cierre del documento = `resume` del mismo hilo, no un proceso aparte. |
| D5 | Checkpointer `SqliteSaver` en `data/checkpoints/` (memoria solo con `RFP_CHECKPOINTER=memory` y en tests). | Persiste ante reinicios del Codespace; la BD de negocio sigue en Supabase. |
| D6 | `request_changes` vuelve al `rfp_section_loop` de la Parte 2 del mismo departamento; `reject` exige regenerar los borradores. | Pregunta de diseño 1: corregir no reinicia el flujo; rechazar sí pide una nueva ejecución. |
| D7 | Validación con `ApprovalDecision` (aprobador = responsable, motivo ≥ 10 caracteres) antes de `Command(resume)`. | Una respuesta mal formada nunca entra al grafo. |
| D8 | Triggers deterministas sobre el estado (volumen del handoff, monedas por sección, regla de 48 h de la Parte 2), al abrir y antes de cerrar. | Pregunta de diseño 3; un humano puede aprobar un borrador provisional. |
| D9 | Árbitro = regla del BRIEFING firmada por el árbitro nombrado; reescritura forzada por la rama; 2 rondas, después rechazo. Sin país → `blocked`. | «Los agentes solo señalan»; nada de LLM votando. |
| D10 | Capacidad de referencia: Los Ángeles 20.000 y Zaragoza 15.000 pedidos/mes (configurable). | El BRIEFING no la da; como el tarifario de la Parte 2. |
| D11 | Rechazo → ticket en `esperando_aprobación` + `stage = seccion_rechazada`. | No se inventan estados; el ticket sigue sin todos los vistos buenos. |
| D12 | Traza en el estado de cada hilo y en `rfp_trace_events`, también para las Partes 1 y 2. | «Qué agente hizo qué y en qué orden» de punta a punta. |

## 3. Commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan de la aprobación humana y el cierre de RFPs` |
| 2 | Contratos y configuración | `feat: añade los contratos y la configuración de la aprobación de RFPs` |
| 3 | Triggers | `feat: detecta los triggers de conflicto del BRIEFING en estado estructurado` |
| 4 | Árbitro | `feat: añade el nodo de arbitraje con el árbitro fijo del BRIEFING` |
| 5 | Documento | `feat: consolida las secciones aprobadas en el documento final` |
| 6 | Traza | `feat: registra la traza de cada nodo con agente, input, output y hora` |
| 7 | Grafos | `feat: añade los grafos de aprobación por departamento y de cierre del ticket` |
| 8 | Checkpointer | `feat: guarda el estado de los grafos en un checkpointer SQLite por ticket y departamento` |
| 9 | Persistencia | `feat: persiste aprobaciones, documento final y traza en PostgreSQL` |
| 10 | Servicio | `feat: añade el servicio de aprobación con resume por rama` |
| 11 | Traza Partes 1-2 | `feat: traza también los nodos de las Partes 1 y 2` |
| 12 | API | `feat: encadena la Parte 3 y añade las rutas de aprobación, traza y documento` |
| 13 | UI | `feat: permite aprobar, pedir cambios o rechazar cada sección desde el backoffice` |
| 14 | E2E | `feat: añade la ruta E2E reproducible de las Partes 1 a 3 con aprobaciones simuladas` |
| 15 | CLI | `feat: añade el runner CLI de la aprobación de RFPs` |
| 16 | Helpers de test | `test: añade los helpers y el checkpointer en memoria para las pruebas de la Parte 3` |
| 17 | Tests reglas | `test: cubre los triggers, el árbitro, la decisión humana y el documento final` |
| 18 | Tests grafo | `test: cubre interrupción, reanudación, ramas en paralelo, límites y arbitraje` |
| 19 | Tests E2E + SQL | `test: añade la prueba E2E y la del almacén SQL de la Parte 3` |
| 20 | Tests rutas | `test: añade las rutas de aprobación y actualiza el contrato de rutas` |
| 21 | CI | `ci: ejecuta las pruebas de la Parte 3 de RFPs` |
| 22 | Diseño | `docs: documenta la aprobación humana y el cierre del documento de RFPs` |
| 23 | `progress.md` | `docs: registra la Parte 3 de RFPs en progress` |

## 4. Verificación (Marisin, en el Codespace)

| # | Paso | Criterio |
|---|---|---|
| V1 | `uv add langgraph-checkpoint-sqlite` | commit `chore:` propio |
| V2 | `services/sql/005_rfp_approval.sql` en Supabase | 5 tablas: 24 / 10 / 18 / 13 / 20 columnas |
| V3 | pytest Parte 3, rutas y suite completa | todo en verde (contrato de 51 rutas) |
| V4 | `--e2e all --out …/e2e-all.json` | 4 escenarios ✓ |
| V5 | UI: «Pedir aprobación» en Luna; aprobar lastmile con warehouse en pausa; pedir cambios; aprobar | `terminado` + documento final |
| V6 | «Ver traza» y `--show` | traza completa y JSON del ticket |

## 5. Registro

* 2026-11-26 — Plan e implementación preparados por Claude en un parche (`rfp-approval-completion.patch`). Probado en el entorno de Claude con un doble local de LangGraph (StateGraph, `Send`, `interrupt`, `Command(resume)`, `InMemorySaver`/`SqliteSaver`): reglas 18 tests, grafos 15, E2E 5 (los 4 escenarios), y los 107 tests previos de RFP siguen en verde; tipos de la página con `tsc`. Sin LangGraph real, FastAPI ni SQLModel en ese entorno: rutas, almacén SQL y el checkpointer real los verifica Marisin (V3). Pendiente de Marisin: V1–V6.
* 2026-11-26 — Verificación de Marisin en el Codespace: SQL 005 en Supabase (24 / 10 / 18 / 20 / 13 columnas); pytest Parte 3 42 passed, rutas 30 passed, suite completa 806 passed, 1 skipped; `--e2e all` con los 4 escenarios ✓. UI con el ticket #2 (Luna): aprobación abierta con tres pausas, lastmile aprobada con warehouse en pausa, cambios pedidos por Ana Whitfield → reescritura → ronda 1, aprobación → `terminado` y documento final; traza de 23 pasos (la rama de warehouse se reanudó desde SQLite tras reiniciarse la API). Tres `fix:` surgidos de la verificación: etapa tras una reescritura, numeración del historial y petición de cambios en `approval_history`. Evidencias en `docs/rfp-approval/evidence/`.
