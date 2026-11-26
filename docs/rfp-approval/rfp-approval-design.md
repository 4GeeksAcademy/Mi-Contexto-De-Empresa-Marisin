# Flujo agéntico de RFPs — Parte 3: aprobación humana y cierre del documento

> Hito 9 · Parte 3 de 3 · rama `feature/rfp-approval-completion` (desde `feature/rfp-response-generation`).
> Código: `data/pipelines/rfp_intake/approval/` · API: `services/rfp/router.py` · UI: `uis/backoffice/src/app/rfp/page.tsx`
> · SQL: `services/sql/005_rfp_approval.sql` · CLI: `scripts/rfp_approval_run.py`.

## 1. Qué resuelve

La Parte 2 deja, en el **mismo ticket**, un borrador evaluado por departamento (`rfp_tickets.drafting_handoff`,
contrato `trackflow.rfp_drafting.handoff/v1`, bandera `ready_for_approval`). La Parte 3 hace que **un humano de cada
departamento dé su visto bueno** antes de que el documento salga hacia el cliente:

1. Cada departamento activo tiene **su propia rama** del grafo, con su propio hilo de checkpointer. La rama se detiene
   con `interrupt()` justo antes de la acción irreversible (aprobar la sección) y espera a su responsable.
2. La pausa de una rama **no bloquea a las demás**: Carlos Vega puede aprobar `lastmile` mientras la rama de
   `warehouse` sigue en pausa esperando a Ana Whitfield.
3. Pedir cambios **vuelve al generador de la Parte 2 del mismo departamento** (no reinicia el flujo), con límite de rondas.
4. Los conflictos entre secciones del BRIEFING §7 se detectan en estado estructurado y los resuelve el **árbitro fijo
   con su regla**, nunca un LLM votando.
5. Con todas las secciones aprobadas y sin conflictos, el **documento final se genera solo** y el ticket pasa a `terminado`.
6. Cada ejecución de nodo de las tres partes queda en la **traza** (agente, input, output, timestamps).

## 2. Fuente de verdad (BRIEFING del Hito 9)

| Tema | BRIEFING | Implementación |
|---|---|---|
| Aprobadores | §2.1 `warehouse` Ana Whitfield · `lastmile` Carlos Vega · `reverse` Sofía Ramos; solo departamentos activos | `ApprovalDecision`: `approver` tiene que ser el responsable del departamento; si no, 422 |
| Aprobación | §6 cada responsable aprueba su sección de forma independiente; sin escalera jerárquica (responsables pares) | una rama por departamento (`rfp-{ticket}:{department}`); no hay CEO ni niveles |
| Documento final | §6 solo con todas las secciones activas aprobadas; §2.3 `FinalDocument` = `ticket_id`, `sections`, `currency`, `generated_at` | `close_document` solo tras `await_signoffs` sin pendientes + `detect_conflicts` vacío; `rfp_final_documents` |
| Estados | §2.3 `esperando_aprobación` (pausa humana por departamento) y `terminado` (documento final generado) | ver §4 |
| `DepartmentSection` | §2.3 `approval_status`, `approver`, `approved_at` | + `approval_round`, `approval_comment`, `approval_requested_at`, `approval_history` |
| Conflictos | §7 `volume-vs-capacity` (Miguel Torres), `returns-sla-breach` (Sofía Ramos / Miguel Torres), `currency-mismatch` (Miguel Torres); los agentes solo señalan | `conflicts.py` + `arbiter.py` (§6) |
| KPIs | §3 tiempo de aprobación por departamento; tiempo de armado < 2 días | `approval_minutes` por sección y `proposal_hours` en `FinalDocument.metrics` |

## 3. Arquitectura

```
                     rfp_approval  (hilo rfp-{ticket_id})
 START → load_drafts → detect_conflicts ─conflicto─→ arbitrate ─rechazo / bloqueo─→ reject_ticket → END
                             │ sin conflicto            │ request_changes forzado
                             ↓                          ↓
                       open_branches ←──────────────────┘     (arranca o reabre ramas EN PARALELO)
                             ↓
                      await_signoffs ⏸ interrupt ⟲            (un SignoffEvent por rama que termina)
                             │ todas aprobadas                └─ alguna rechazada → reject_ticket
                             ↓
                      detect_conflicts (sobre lo aprobado) ─sin conflicto─→ close_document → END

            rfp_department_approval  (hilo rfp-{ticket_id}:{department_id}, uno por rama)
 START → prepare_review ─forzado por el árbitro─→ revise_section (generador + evaluadores de la Parte 2)
              └──────────────────────────────→ request_approval ←───────┘
                                                     ↓
                      ┌───────────────────── human_approval ⏸ interrupt(ApprovalRequest)
                      │  approve / reject            └─ request_changes con rondas → revise_section
                      └──────────────────→ record_signoff → END        (sin rondas → rechazada)
```

- **`resume` es una entrada explícita**: `ApprovalService.decide()` valida la respuesta y hace
  `Command(resume=decisión)` sobre `rfp-{ticket}:{department}`. LangGraph continúa en `human_approval`
  (el nodo vuelve a ejecutarse desde su inicio; nada antes del `interrupt` tiene efectos). Nunca se reinicia desde `START`.
- Cuando una rama termina, `notify()` reanuda el hilo del ticket con su `SignoffEvent` (`Command(resume=…)` sobre `rfp-{ticket}`).
- **Por qué dos grafos y no un `Send` con `interrupt` dentro**: con ramas en el mismo superstep, una rama que pide
  cambios no podría volver al generador hasta que las demás respondieran (el superstep no avanza). Con un hilo por
  rama, cada departamento recorre su ciclo `human_approval → revise_section → human_approval` sin esperar a nadie.
- Las ramas se ejecutan en hilos del sistema propios (`ThreadPoolExecutor`), no dentro del contexto del nodo del
  ticket: cada `invoke` de una rama es una ejecución de primer nivel con su `thread_id`; su `interrupt` no puede
  propagarse al grafo del ticket ni a otra rama.

## 4. Estados del ticket (misma fila, nombres del BRIEFING)

| Estado | Etapa (`stage`) | Cuándo |
|---|---|---|
| `en_evaluación` / `needs_human_review` | `borradores_listos` | entrada desde la Parte 2 (`ready_for_approval = true`) |
| `esperando_aprobación` | `esperando_aprobaciones` | alguna rama en pausa esperando a su responsable |
| `esperando_aprobación` | `arbitrando` / `revisando_secciones` | el árbitro decidió / una rama se reescribe |
| `esperando_aprobación` | `generando_documento` | todas aprobadas, se consolida el documento |
| `esperando_aprobación` | `seccion_rechazada` | una sección rechazada (humano, límite de rondas o arbitraje): no hay documento; se relanza la Parte 2 |
| `terminado` | `documento_final` | documento guardado en `rfp_final_documents` y accesible en `GET /rfp/tickets/{id}/document` |

No se inventan estados: un rechazo deja el ticket en `esperando_aprobación` (sigue sin el visto bueno de todos) con una etapa que lo explica.

`approval_status` de cada sección: `pendiente` → (`cambios_solicitados` → `pendiente`)* → `aprobada` | `rechazada`.

## 5. Human-in-the-loop

**Validación antes del resume** (`schemas.ApprovalDecision`, `ApprovalService.submit`):

- `decision` ∈ `approve | reject | request_changes`; sin campos extra.
- `approver` = responsable del BRIEFING para ese departamento (`solo Ana Whitfield puede aprobar la sección de warehouse`).
- `comment` obligatorio (≥ 10 caracteres) para rechazar o pedir cambios: es el feedback del generador.
- La rama tiene que estar interrumpida en `human_approval` y la sección en `pendiente` (un segundo envío → 409).
- Si algo no cuadra, la API responde 422/409 y **el grafo no se toca** (test `test_an_invalid_decision_never_reaches_the_graph`).

**Lo que ve el responsable** (`ApprovalRequest`, pregunta de diseño 2): ronda y máximo, si el borrador es provisional
(`needs_human_review`), las reglas de cumplimiento que fallan, los aspectos sin responder, las notas del árbitro sobre
su sección y el último comentario. Con eso decide sin releer el documento entero; el borrador completo está debajo.

**Rechazo vs. pedir cambios** (pregunta de diseño 1):

- `request_changes` → vuelve al **generador de la Parte 2 de ese departamento** dentro de la misma rama
  (`revise_section` ejecuta `rfp_section_loop` con el borrador actual y el comentario como feedback, reevaluado por los
  tres evaluadores), y la rama se vuelve a pausar. Límite: `RFP_APPROVAL_MAX_ROUNDS` (3). Pedir cambios con las rondas
  agotadas deja la sección **rechazada**.
- `reject` → la sección queda rechazada y el ticket en `seccion_rechazada`: requiere **una nueva ejecución** (botón
  «Regenerar borradores» o `POST /rfp/tickets/{id}/drafts`), que reinicia la Parte 2 y, al terminar, abre una aprobación nueva.

## 6. Arbitraje (BRIEFING §7) — pregunta de diseño 3

Los triggers se calculan con datos estructurados en `detect_conflicts` (al abrir las ramas y otra vez sobre lo
aprobado antes de cerrar, porque un humano puede aprobar un borrador provisional):

| Trigger | Detección | Árbitro | Regla (mientras quedan rondas) | Límite agotado |
|---|---|---|---|---|
| `volume-vs-capacity` | `warehouse` y `lastmile` activos y el volumen que asume `lastmile` (handoff, o el fijado por el árbitro, y los «N pedidos al mes» de su sección, sin contar citas de la RFP ni tramos de la tabla) > capacidad del almacén (`RFP_CAPACITY_LOS_ANGELES` 20.000, `RFP_CAPACITY_ZARAGOZA` 15.000 pedidos/mes) | Miguel Torres | `request_changes` a `lastmile` (y a `warehouse` si también cotiza por encima) con `monthly_volume` = capacidad | rechazo |
| `returns-sla-breach` | `check_returns_turnaround` de la Parte 2 sobre **todas** las secciones | Sofía Ramos (su sección) / Miguel Torres (otra) | `request_changes` forzado: «nunca menos de 48 h; el plazo es 72 h» | rechazo (sin documento) |
| `currency-mismatch` | monedas citadas por sección vs. moneda del país (US→USD, Spain→EUR) | Miguel Torres | reescribir en la moneda del país | rechazo; sin país → `blocked` |

- Cada decisión es una `ArbitrationDecision` con `mode = "rule"`, `arbiter`, `rule`, `round`, `action` y `data`:
  queda en el estado, en `approval_history` de la sección, en la traza y en el documento final.
- `RFP_ARBITRATION_MAX_ROUNDS` (2): cada ronda reabre solo las secciones ofensoras (las demás conservan su aprobación);
  en la ronda 3 el árbitro rechaza.
- La capacidad de los almacenes no está en el BRIEFING: como el tarifario de la Parte 2, es la capacidad de referencia del proyecto, configurable por entorno.

## 7. Checkpointer e identidad de los hilos

- `SqliteSaver` (`langgraph-checkpoint-sqlite`) en `data/checkpoints/rfp_approval.sqlite` (`RFP_CHECKPOINT_PATH`,
  ignorado por git). `RFP_CHECKPOINTER=memory` solo para desarrollo; los tests usan un `InMemorySaver` nuevo por test.
- `thread_id`: `rfp-{ticket_id}` (ticket) y `rfp-{ticket_id}:{department_id}` (rama). Tickets concurrentes nunca
  comparten checkpoint (`test_concurrent_tickets_do_not_share_checkpoints`).
- Abrir la aprobación otra vez (`--start --force`, botón «Reiniciar la aprobación» o tras regenerar la Parte 2) borra
  esos hilos antes de empezar: una aprobación nueva nunca hereda un checkpoint viejo.
- Si la API se reinicia con aprobaciones pendientes, la rama se reanuda desde el SQLite
  (`test_a_branch_resumes_from_sqlite_after_a_restart`).
- Concurrencia: un candado por hilo en el proceso de la API (un solo worker de uvicorn). Con varios workers habría
  que cambiarlo por un candado de PostgreSQL (`pg_advisory_xact_lock`).

## 8. Trazabilidad

`trace.traced()` envuelve cada nodo de la Parte 3 y añade al estado (`trace`, reductor de suma) y a
`rfp_trace_events`: `graph`, `thread_id`, `department_id`, `node`, `agent`, `status` (`ok` | `interrupted` | `error`),
`input`, `output` (resumidos), `started_at`, `finished_at`, `duration_ms`. Los runners de las Partes 1 y 2 registran
también sus nodos, así que `GET /rfp/tickets/{id}/trace` muestra, en orden, la ejecución completa del ticket: del
conversor y el clasificador al `ultimate_document_synthesizer`. La UI la muestra con «Ver traza».

## 9. API (contrato de rutas 47 → 51)

| Ruta | Respuesta |
|---|---|
| `POST /rfp/tickets/{id}/approvals` | 202 · abre (o reinicia) la aprobación; 409 sin borradores listos o terminado |
| `POST /rfp/tickets/{id}/approvals/{department_id}` | 202 · `{decision, approver, comment}`; aprobar/rechazar reanuda al momento (`resumed: true`), pedir cambios sigue en segundo plano; 422 decisión no válida; 409 la rama no espera aprobación |
| `GET /rfp/tickets/{id}/trace` | 200 · eventos en orden |
| `GET /rfp/tickets/{id}/document` | 200 · `FinalDocument` + Markdown; 404 hasta `terminado` |

`GET /rfp/tickets/{id}` añade `approval_requests` (el `ApprovalRequest` de cada rama en pausa) y `final_document_available`.
Encadenado: Parte 1 → Parte 2 → Parte 3 en las tareas de fondo del `POST` (`RFP_AUTO_APPROVAL=0` lo desactiva).

## 10. Ruta E2E reproducible

`python scripts/rfp_approval_run.py --e2e all` (y `tests/pipelines/test_rfp_approval_e2e.py`, mismo código en
`approval/e2e.py`): grafo `rfp_intake` real sobre la muestra del BRIEFING → grafo `rfp_drafting` real → Parte 3 con
SQLite en disco y **un servicio nuevo en cada decisión** (como si la API se reiniciara). Escenarios:

| Escenario | Qué demuestra |
|---|---|
| `parallel` | Luna: B (lastmile) aprobada con A (warehouse) en pausa; decisión inválida rechazada sin tocar el grafo; `request_changes` → generador → nueva pausa; aprobación → documento final |
| `returns` | ModaViva: reverse llega de la Parte 2 prometiendo 24 h → Sofía Ramos fuerza la reescritura → documento con el arbitraje |
| `volume` | Luna con 30.000 pedidos/mes → Miguel Torres limita la propuesta a 20.000 → documento coherente |
| `limit` | el generador insiste en 24 h → el arbitraje agota sus rondas → sección rechazada, sin documento |

## 11. Limitaciones conocidas

- Aprobar la última sección ejecuta el cierre en la misma petición; si el detector reabre una sección, su reescritura
  (LLM) también va en esa petición. Pedir cambios siempre va en segundo plano.
- Los candados son de proceso (ver §7).
- Un fallo a mitad de una reescritura deja la etapa en `error` con su mensaje; se reinicia la aprobación con
  «Reiniciar la aprobación» o `--start N --force`.
