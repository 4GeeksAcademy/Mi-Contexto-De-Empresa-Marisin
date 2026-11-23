# Flujo agéntico de RFPs — Parte 2: generación y evaluación de respuestas (TrackFlow)

La Parte 1 (`docs/rfp-intake/rfp-intake-design.md`) deja cada RFP válida en `analisis_completo` con su handoff
(`trackflow.rfp_intake.handoff/v1`): qué pide el cliente a cada departamento. La Parte 2 convierte ese análisis en
un **primer borrador de la propuesta económica por departamento**, revisado automáticamente antes de que lo vea
una persona.

## 1. Fuente de verdad (BRIEFING)

- **Departamentos** (§2.1): `warehouse` (Ana Whitfield), `lastmile` (Carlos Vega), `reverse` (Sofía Ramos). Solo se
  redactan los que la Parte 1 activó.
- **Estados de la Parte 2** (§2.3): `generando_borrador`, `en_evaluación`, `needs_human_review`. Los de la Parte 3
  (`esperando_aprobación`, `terminado`) no se escriben aquí.
- **Lineamientos del evaluador de cumplimiento** (§5), cada uno con su `rule_id`:

| `rule_id` | Regla | Fuente |
|---|---|---|
| `currency-by-country` | USD para Estados Unidos, EUR para España (según `client_country`) | §5 |
| `on-time-sla-stated` | La propuesta indica el SLA de entrega a tiempo (%) | §5 |
| `returns-min-48h` | Nunca prometer procesar devoluciones en menos de 48 h | §5 |
| `volume-discount-table` | Incluye una tabla de descuentos por volumen | §5 |
| `no-carrier-negotiated-rates` | No revela tarifas negociadas con transportistas; solo el precio final | §5 |
| `no-invented-figures` | Ninguna cifra fuera de la RFP, el tarifario o las políticas | §2.3 («nunca inventes») |

- **KPI** (§3): iteraciones medias por sección < 2 → `MAX_ITERATIONS = 3` y la métrica va en el handoff.

## 2. Arquitectura

```
POST /rfp/tickets ─BackgroundTasks─→ Parte 1 (rfp_intake) ─→ analisis_completo + ready_for_drafting
                                 └─→ draft_if_ready_safely ─→ Parte 2 (rfp_drafting)        ← encadenado
POST /rfp/tickets/{id}/drafts (202) ─→ claim + draft_ticket_safely                          ← relanzar
scripts/rfp_drafting_run.py --ticket-id / --pending / --show / --demo                       ← CLI

rfp_drafting (grafo del ticket)
  START → load_handoff ─Send × departamento─→ draft_department ─→ assemble → END
                                                │
                                                └─ rfp_section_loop (subgrafo, uno por departamento)
                                                     START → generate ─Send─→ evaluate_readability ─┐
                                                                      ├Send─→ evaluate_relevance ───┼→ judge
                                                                      └Send─→ evaluate_compliance ──┘   │
                                                     generate ←── falla y quedan iteraciones ───────────┤
                                                     finalize ←── pasa, o límite agotado ───────────────┘ → END
```

- Código en `data/pipelines/rfp_intake/drafting/` (grafo dedicado; nada del grafo de CX ni de los nodos de la Parte 1).
- Un solo backend: la ruta nueva está en `services/rfp/router.py`; el router solo dispara el runner.
- `build_graph(llm, reporter)` fija el LLM y el reporter en cada nodo con un cierre (lección de la Parte 1: sin `config`).

## 3. Agentes

**Generadores (uno por departamento).** `WarehouseGenerator`, `LastMileGenerator` y `ReverseGenerator` comparten una
base pero tienen rol, prompt, frase de cobertura, tabla de precios y condiciones propios. Cada uno recibe solo su
`DraftingInput`: datos del cliente y su entrada del handoff (aspectos clave + preguntas abiertas), su tarifa en la
moneda del país y sus políticas de la base de conocimiento. Estructura obligatoria de la sección:

1. `## Propuesta económica — <departamento>` con cliente, moneda y responsable.
2. «Qué pide el cliente y cómo lo cubre TrackFlow» (un punto por aspecto clave).
3. «Precios» (tabla en la moneda del cliente).
4. «Descuentos por volumen» (tabla + tramo que aplica; sin volumen en la RFP, se dice que falta).
5. «Condiciones de servicio» (SLA 90 %, plazos, onboarding o plazo de devoluciones de 72 h).
6. «Datos pendientes del cliente» (las preguntas abiertas de la Parte 1).

Con LLM redacta la sección; en un reintento recibe su borrador anterior y el `feedback_for_generator`. Sin LLM
usa su plantilla determinista, que cumple el BRIEFING.

**Evaluadores (en paralelo, deterministas).**

| Evaluador | Recibe | Pasa si |
|---|---|---|
| Legibilidad | solo el texto | prosa (sin tablas ni citas del cliente) con Fernández Huerta ≥ 40 en español (Flesch-Kincaid ≤ 14 en inglés), ≤ 25 palabras por frase de media y 60–900 palabras en la sección. `py-readability-metrics` cuando hay ≥ 100 palabras de prosa; si no, las mismas fórmulas en `metrics.py` |
| Pertinencia | texto + aspectos clave y preguntas abiertas del departamento + nombre del cliente | cubre cada aspecto (raíces del tema ≥ 50 % o del detalle ≥ 40 %), recoge cada pregunta abierta (≥ 60 %), nombra al cliente, habla de su alcance y tiene precios |
| Cumplimiento | texto + moneda del país + fuentes de anclaje (handoff, tarifario, políticas) | ninguna violación de las seis reglas de §1 |

**Juez.** Une los tres resultados en el `EvaluationResult` y escribe un feedback **accionable por fallo**: la regla,
la frase o cifra que lo causa y qué poner en su lugar (p. ej. «Quita la promesa «…24 horas…»: el procesamiento de
devoluciones nunca baja de 48 horas; usa el plazo del tarifario (72 horas)»).

**Base de conocimiento (opcional del enunciado, incluida).** `drafting/knowledge.py`: por defecto cada generador
recibe sus documentos de `docs/company-knowledge-base/` (el corpus del RAG del Hito 7); con
`RFP_DRAFT_KNOWLEDGE=semantic` busca en Qdrant con `rag.retrieve()` y, si falla, vuelve a los documentos.

**Tarifario de referencia** (`drafting/pricing.py`). Almacenamiento, gracia, larga duración, SLA y ventana de
devolución salen de la base de conocimiento; preparación por pedido, precio final por envío por tramo de peso,
devoluciones por unidad, onboarding y la tabla de descuentos por volumen (0 / 5 / 8 / 12 % por tramos de
pedidos al mes, sobre cargos variables; el almacenamiento solo lo negocia Miguel Torres) son la lista de precios
base del proyecto. Todos son precios finales al cliente.

## 4. `EvaluationResult` (persistido en `rfp_department_sections.evaluation_results`)

```json
{
  "section_id": "3:reverse", "department_id": "reverse", "iteration": 1,
  "readability": {"pass": true, "score": 84.7, "details": {"metric": "fernandez_huerta", "avg_words_per_sentence": 10.8, "…": "…"}},
  "relevance": {"pass": true, "missing_aspects": [], "details": {"aspects_total": 4, "…": "…"}},
  "compliance": {"pass": false, "rule_ids": ["currency-by-country", "on-time-sla-stated", "returns-min-48h",
                 "volume-discount-table", "no-carrier-negotiated-rates", "no-invented-figures"],
                 "violations": [{"rule_id": "returns-min-48h", "detail": "Promete procesar devoluciones en menos de 48 horas.",
                                 "evidence": "Plazo de procesamiento de cada devolución: 24 horas desde que llega al almacén."}]},
  "overall_pass": false,
  "feedback_for_generator": "- [returns-min-48h] Quita la promesa «…»: … usa el plazo del tarifario (72 horas).",
  "evaluated_at": "2026-11-23T10:00:00+00:00"
}
```

## 5. Estado del ticket y persistencia (PostgreSQL / Supabase)

| Momento | `rfp_tickets.status` / `stage` | Sección (`draft_status`) |
|---|---|---|
| `claim_for_drafting` (sale de la cola) | `generando_borrador` / `generando_secciones` | — |
| El generador escribe | — | `generando_borrador` (+ `iterations`) |
| Primer borrador listo | `en_evaluación` / `evaluando_secciones` | `en_evaluación` (+ `draft_content`) |
| Juez | — | `evaluation_results` + entrada en `evaluation_history` |
| Fin de la sección | — | `evaluacion_superada` o `needs_human_review` |
| Fin del ticket | `en_evaluación` o `needs_human_review` / `borradores_listos` | — |
| Fallo | sigue el estado / `error` (+ `error_stage`) | lo generado se conserva |

`services/sql/004_rfp_drafting.sql` (idempotente) añade `rfp_tickets.drafting_handoff`, `ready_for_approval`
(+ índice parcial = cola de la Parte 3) y las etapas nuevas al check de `stage`; y a `rfp_department_sections`
`draft_status`, `iterations`, `evaluation_history` y `draft_source`. Un relanzamiento con `force` limpia los
borradores anteriores; reprocesar la Parte 1 borra también los de la Parte 2.

## 6. Handoff a la Parte 3 (`rfp_tickets.drafting_handoff`)

Contrato `trackflow.rfp_drafting.handoff/v1`: `ticket_id`, cliente y moneda, `status`, `needs_human_review`
(departamentos provisionales), una entrada por sección (`draft_status`, `provisional`, `iterations`,
`draft_content`, `evaluation_result` y el historial sin borradores intermedios), los `conflicts` de la Parte 1 y
`metrics` (`avg_iterations`, `first_pass_sections`). `next_status = esperando_aprobación` (lo escribe la Parte 3).
Las secciones `needs_human_review` **van incluidas**: el ticket nunca se descarta.

## 7. Preguntas de diseño

**¿Qué información necesita cada evaluador? ¿Solo la sección o el documento?** Solo la sección y lo mínimo para
juzgarla, enviado con un `Send` por evaluador: legibilidad → el texto; pertinencia → el texto, los aspectos y
preguntas de **su** departamento y el nombre del cliente; cumplimiento → el texto, la moneda del país y las fuentes
de anclaje. Ninguno ve el documento ni otras secciones (`test_each_evaluator_receives_only_what_it_needs`).

**¿Cómo evitas conflictos entre evaluadores en paralelo?** Cada uno devuelve solo su clave de `checks`
(`readability` / `relevance` / `compliance`) y el reductor `merge_checks` las une; nadie escribe la clave de otro.
Cada resultado lleva su `iteration` y el juez rechaza resultados de otra iteración. Los departamentos tienen cada
uno su propio estado de subgrafo, así que tampoco comparten `checks`.

**¿Cómo ve Ventas que un borrador es provisional?** El ticket queda en `needs_human_review` (insignia naranja), la
sección lleva «Provisional · revisión humana», un aviso con el número de iteraciones, las reglas que falla con la
frase exacta, lo que no responde, el feedback y el historial; el handoff lo marca `provisional: true`.

**¿El feedback es específico?** Sí: una línea por fallo con el `rule_id`, la evidencia (frase o cifras) y la
corrección concreta del tarifario; para pertinencia, la lista de aspectos y preguntas sin responder; para
legibilidad, la métrica y el umbral. El generador lo recibe junto a su borrador anterior.

## 8. Verificación

| # | Comprobación | Dónde |
|---|---|---|
| V1 | Generadores por departamento, plantillas que pasan la evaluación, entrada solo desde el handoff | `tests/pipelines/test_rfp_drafting_generators.py` |
| V2 | Reglas del BRIEFING una a una (incluido el fallo de devoluciones < 48 h), legibilidad, pertinencia y forma del `EvaluationResult` | `tests/pipelines/test_rfp_drafting_evaluators.py` |
| V3 | Ciclo: a la primera, corrección con feedback, límite agotado, departamentos independientes, payload mínimo | `tests/pipelines/test_rfp_drafting_graph.py` |
| V4 | Estados en tiempo real, cola, fallo con `stage = error`, encadenado tras la Parte 1, sin leer el PDF | `tests/pipelines/test_rfp_drafting_runner.py` |
| V5 | Persistencia en SQL | `tests/pipelines/test_rfp_drafting_sql_store.py` |
| V6 | `POST /rfp/tickets/{id}/drafts` (202/404/409) y recorrido completo POST → Parte 1 → Parte 2 | `tests/test_rfp_routes.py` |
| V7 | Evidencias con el LLM real y demos del ciclo | `docs/rfp-drafting/evidence/` |

## 9. Limitaciones

- Los evaluadores miden reglas, no la calidad comercial del texto: la aprobación humana es la Parte 3.
- La pertinencia compara raíces de palabras: un sinónimo lejano puede contar como «sin responder» (el feedback lo
  señala y el generador lo nombra en la siguiente iteración).
- `metrics.py` usa la fórmula de Fernández Huerta tal como se publicó (frases por 100 palabras); por eso el
  evaluador también limita las palabras por frase.
- El tarifario de referencia es del proyecto: con precios reales, basta con cambiar `drafting/pricing.py`.
