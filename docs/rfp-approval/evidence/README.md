# Evidencias — Flujo agéntico de RFPs, Parte 3 (aprobación humana y cierre del documento)

Ejecutadas en el Codespace el 26/11/2026 sobre la rama `feature/rfp-approval-completion`, con Supabase, el LLM de
4Geeks y el checkpointer SQLite (`langgraph-checkpoint-sqlite` 3.1.3). Las capturas de la UI marcadas como
«compuestas» juntan recortes de la **misma** pantalla en el mismo momento, separados por una línea gris, para que se
vea a la vez de qué ticket son, la traza y los formularios; no se ha editado nada. Diseño: `../rfp-approval-design.md`.

## Base de datos y tests

| Evidencia | Qué demuestra |
|---|---|
| `rfp-approval-supabase-columns.png` | `services/sql/005_rfp_approval.sql` aplicado: `rfp_department_sections` 24, `rfp_final_documents` 10, `rfp_metadata` 18, `rfp_tickets` 20 y `rfp_trace_events` 13 columnas. |
| `rfp-approval-tests-pipelines.png` | `pytest tests/pipelines -k rfp_approval -q` → **42 passed**: triggers y árbitro del BRIEFING §7, validación de la decisión humana, interrupción y reanudación en el mismo nodo, **aprobar B mientras A sigue interrumpida**, `request_changes` → generador de la Parte 2, límite de rondas y de arbitraje, hilos por ticket, reanudación desde SQLite tras «reiniciar», traza y almacén SQL. |
| `rfp-approval-tests-routes.png` | `pytest tests/test_rfp_routes.py tests/test_serialization_contracts.py -q` → **30 passed**: recorrido real POST → Partes 1, 2 y 3 → aprobaciones por la API → documento; 422/409 antes de tocar el grafo; contrato de **51** rutas. |
| `rfp-approval-tests-all.png` | `python -m pytest -q` → **806 passed, 1 skipped** (47 más que en la Parte 2, sin romper nada). |

## Ruta E2E reproducible (`scripts/rfp_approval_run.py --e2e all`)

| Evidencia | Qué demuestra |
|---|---|
| `rfp-approval-e2e.png` · `e2e-all.json` | Partes 1 → 3 sin BD ni LLM, con checkpointer SQLite en disco y un servicio nuevo en cada decisión. Los cuatro escenarios con todas sus comprobaciones ✓: `parallel` (9), `returns` (7), `volume` (5) y `limit` (4); hilos `rfp-1`, `rfp-1:<departamento>`; línea de tiempo de estados, documento final y traza en el JSON. |

## UI del backoffice — ticket #2, Luna Cosmetics (`/rfp`)

El ticket se analizó y redactó el 23/11 (Partes 1 y 2) y se aprobó el 26/11 con el código de esta rama.

| Evidencia | Qué demuestra |
|---|---|
| `rfp-approval-ui-esperando.png` (compuesta) | 14:31: «Pedir aprobación» → ticket en «Esperando aprobación». La traza (10 pasos) muestra `detect_conflicts` sin conflictos, las dos ramas abiertas en paralelo y **tres pausas** independientes: `human_approval` de warehouse (Ana Whitfield), de lastmile (Carlos Vega) y `await_signoffs` del ticket. Las dos secciones «Pendiente de aprobación», ronda 0 de 3, cada una con su formulario. |
| `rfp-approval-ui-b-aprobada.png` (compuesta) | 14:57: Carlos Vega aprueba lastmile **mientras warehouse sigue en pausa**. Pasos 11-14: la rama de lastmile se reanuda en `human_approval` (sin repetir `prepare_review` ni `request_approval`), `record_signoff`, el ticket recibe el sign-off y vuelve a pausarse; ninguna fila nueva de warehouse. Ticket aún «Esperando aprobación», sin documento. |
| `rfp-approval-ui-cambios.png` (compuesta) | 15:13: Ana Whitfield pide cambios («Añade en la primera línea que el onboarding dura 10 días hábiles.»). «Reescribiendo (cambios pedidos)» → la sección vuelve con «Onboarding: 10 días hábiles desde la firma.» en la primera línea, pasa los tres evaluadores y queda «Pendiente» en la **ronda 1 de 3**. Pasos 15-18: `human_approval` → `revise_section` (generador + evaluadores de la Parte 2) → `request_approval` → `human_approval` ⏸. Lastmile sigue aprobada. |
| `rfp-approval-ui-terminado.png` (compuesta) | 15:43: Ana aprueba → ticket **«Terminado»** / «Documento final generado» un segundo después. Documento para Ventas (Miguel Torres) en USD, descargable en `.md`, con cada sección tal como se aprobó y su «✅ Aprobada por…»; las dos secciones aprobadas con su `approved_at`. El historial distingue la reescritura de la aprobación. |
| `rfp-approval-ui-traza.png` (compuesta) | Los 23 pasos de la Parte 3, en orden, con grafo, rama, nodo, agente y hora. Pasos 19-23: la rama de warehouse se reanuda desde el checkpointer SQLite tras el reinicio de la API (se aplicó un `fix:` con la rama en pausa), `record_signoff`, `await_signoffs`, `detect_conflicts` sobre lo aprobado y `close_document` (`ultimate_document_synthesizer`). |
| `ticket-2-approval.json` | `--show 2`: `terminado` / `documento_final`; ramas `rfp-2:warehouse` y `rfp-2:lastmile` sin espera pendiente; `approver` / `approved_at` por sección; KPI del BRIEFING §3: **25,5 min** (lastmile) y **29,33 min** (warehouse, desde que se volvió a pedir su aprobación tras la reescritura) de tiempo de aprobación, 1 ronda de revisión, sin arbitrajes; documento final completo con el «Registro de aprobaciones» y la traza. |

## Observaciones

- La traza del ticket #2 empieza en la Parte 3: sus Partes 1 y 2 se ejecutaron el 23/11, antes de que existiera la
  traza. Un ticket subido con esta rama la tiene completa desde `rfp_intake` (lo comprueban
  `test_the_three_parts_chain_and_each_responsible_approves_independently` y `e2e-all.json`).
- El «tiempo de armado» del documento (73,45 h) cuenta desde la carga del 23/11, no desde que existe la Parte 3.
- Dos correcciones `fix:` surgieron de esta verificación: la etapa del ticket no volvía a «Esperando el visto bueno»
  tras una reescritura, y el historial numeraba igual las iteraciones de la Parte 2 y las de la reescritura. Una
  tercera, posterior a estas capturas, añade la petición de cambios del responsable a `approval_history` (antes solo
  estaba en el estado del grafo y en la traza); el JSON del ticket #2 es anterior a ella.
- El visor Markdown de la página es mínimo (muestra literales las comillas invertidas, el `>` y las fechas ISO);
  el `.md` descargado se ve bien.
