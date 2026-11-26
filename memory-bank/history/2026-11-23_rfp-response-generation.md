# Plan y registro — Flujo Agéntico de RFPs: Generación de Respuestas · Parte 2 de 3 (TrackFlow)

> **Proyecto 4Geeks:** "Hito — Flujo Agéntico de RFPs: Generación de Respuestas (Parte 2 de 3)".
> **Rama:** `feature/rfp-response-generation`, creada **desde `feature/rfp-intake`** (PR #34 sin mergear; encadena sobre #29–#33).
> **Dependencias nuevas:** ninguna (`langgraph`, `py-readability-metrics` y SQLModel ya están). El parche no toca `pyproject.toml` ni `uv.lock`.
> **BRIEFING:** `content/contexts/09-agentic-workflows/trackflow-BRIEFING.es.md` (§2.3 estados y entidades, §3 KPIs, §5 lineamientos, §6 entregable de la Parte 2).

## 0. Reglas
1. Un commit por acción, prefijo convencional y descripción en español.
2. Partir del handoff de la Parte 1 (`rfp_tickets.handoff` + `ready_for_drafting`): nunca re-parsear el PDF ni el Markdown.
3. Sin API nuevo: una ruta más en `services/rfp/router.py`; grafo y agentes en `data/pipelines/rfp_intake/drafting/`; CLI en `scripts/`.
4. Borradores y `evaluation_results` en PostgreSQL (Supabase); nunca TinyDB ni JSON.
5. Estados exactamente los del BRIEFING para la Parte 2; no se escriben `esperando_aprobación` ni `terminado`.
6. No se edita ningún `.env*`: las variables nuevas (`RFP_DRAFT_MAX_ITERATIONS`, `RFP_AUTO_DRAFT`, `RFP_DRAFT_KNOWLEDGE`) tienen valor por defecto.

## 1. Rúbrica → dónde se cumple

| Criterio | Dónde |
|---|---|
| Un agente generador por departamento, separado | `drafting/generators.py`: `WarehouseGenerator`, `LastMileGenerator`, `ReverseGenerator` (rol, tarifa, plantilla y prompt propios) |
| Consume el handoff de la Parte 1, sin re-parsear el PDF | `drafting/handoff.py` (`validate_input`, `drafting_inputs`); cola `ready_for_drafting` + `claim_for_drafting`; test con `pdf_to_markdown` y `get_markdown` que fallan si se llaman |
| Evaluadores en paralelo; departamentos sin bloquearse | Subgrafo `rfp_section_loop`: `Send` a `evaluate_readability` / `evaluate_relevance` / `evaluate_compliance`; `Send` por departamento en `rfp_drafting`, cada uno con su ciclo |
| Ciclo generador-evaluador con límite y `needs_human_review` | `nodes.route_after_judge` (`MAX_ITERATIONS = 3`); `finalize` conserva último borrador + `EvaluationResult`; handoff a la Parte 3 los incluye |
| Ticket en tiempo real | `runner.StoreReporter`: `generando_borrador` → `en_evaluación` → (`needs_human_review`); estado por sección; UI con poll |
| `EvaluationResult` estructurado | `drafting/schemas.py` (forma del enunciado, `pass` como alias) |
| Persistencia en PostgreSQL, un solo backend | `services/sql/004_rfp_drafting.sql` + `sql_store.py`; `POST /rfp/tickets/{id}/drafts` en el router existente |
| Tests: éxito, fallo genérico y fallo de compliance anclado al BRIEFING | `tests/pipelines/test_rfp_drafting_{generators,evaluators,graph,runner,sql_store}.py` (`test_briefing_rule_returns_under_48_hours_fails_compliance`) |
| Lineamientos del BRIEFING §5 | `drafting/config.py` (`COMPLIANCE_RULES` con `rule_id`) + `evaluators.py` |

## 2. Decisiones (D1–D10)

| # | Decisión | Por qué |
|---|---|---|
| D1 | Base `feature/rfp-intake` (PR encadenado). | El PR #34 no está en `main`. |
| D2 | La Parte 2 se encadena sola tras la Parte 1 (segunda tarea de fondo, en orden) y se puede relanzar con `POST /rfp/tickets/{id}/drafts` (202) o el CLI. | Ventas quiere el borrador sin pasos manuales; los tickets ya analizados antes de esta rama se lanzan con el botón. |
| D3 | Cola = `ready_for_drafting`; `claim_for_drafting` la baja de forma atómica (`SELECT … FOR UPDATE`). | Ningún ticket se redacta dos veces a la vez. |
| D4 | Subgrafo por departamento (`rfp_section_loop`) ejecutado dentro de cada `Send` del grafo del ticket. | El bucle de un departamento no espera al de otro (no van en paso de supersteps compartidos). |
| D5 | Evaluadores **deterministas** (legibilidad con `py-readability-metrics` + Fernández Huerta, pertinencia por cobertura de los aspectos del handoff, cumplimiento con una regla por lineamiento). | El enunciado pide reglas concretas, no una opinión del agente; mismo borrador → mismo resultado, sin bucles por un juez caprichoso, y cada fallo trae su evidencia. El LLM está en el generador. |
| D6 | Payload mínimo por evaluador vía `Send`; cada uno escribe solo su clave de `checks` (reductor de mezcla) con su `iteration`; el juez valida la iteración. | Preguntas de diseño 1 y 2. |
| D7 | Generador: LLM con prompt de rol + reglas + tarifa + políticas; en reintento recibe su borrador y el feedback. Sin LLM, plantilla del departamento (cumple el BRIEFING). | Robusto si el LLM cae; la plantilla es la referencia de una sección correcta. |
| D8 | Precios: base de conocimiento (almacenamiento 18 USD/16 EUR por m³, SLA 90 %, etc.) + tarifario de referencia del proyecto (`drafting/pricing.py`). | El BRIEFING no da precios; nada de cifras inventadas: todo número del borrador tiene que estar en el handoff, el tarifario o las políticas (`no-invented-figures`). |
| D9 | `MAX_ITERATIONS = 3`. | KPI del BRIEFING: < 2 iteraciones de media; deja dos correcciones antes de pedir revisión humana. |
| D10 | Ticket final: `needs_human_review` si alguna sección agotó el límite; si no, sigue `en_evaluación` con `stage = borradores_listos`. `drafting_handoff` + `ready_for_approval` para la Parte 3. | No se inventan estados de la Parte 3; la etapa interna dice que terminó. |

## 3. Commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan de la generación y evaluación de respuestas a RFPs` |
| 2 | Configuración, tarifario y contratos | `feat: añade el tarifario de referencia y los contratos de la Parte 2 de RFPs` |
| 3 | Base de conocimiento | `feat: da acceso al generador a la base de conocimiento de TrackFlow` |
| 4 | Generadores | `feat: añade un agente generador por departamento para la propuesta económica` |
| 5 | Evaluadores y juez | `feat: añade los evaluadores de legibilidad, pertinencia y cumplimiento del BRIEFING` |
| 6 | Entrada/salida del handoff | `feat: consume el handoff de la Parte 1 y arma el de la Parte 3` |
| 7 | Grafo | `feat: añade el grafo rfp_drafting con el ciclo generador-evaluador` |
| 8 | Persistencia | `feat: persiste borradores y evaluaciones de las secciones en PostgreSQL` |
| 9 | Runner | `feat: añade el runner de la Parte 2 con progreso del ticket en tiempo real` |
| 10 | API | `feat: encadena la Parte 2 tras el análisis y permite relanzar los borradores` |
| 11 | UI | `feat: muestra los borradores y su evaluación en la página de RFPs` |
| 12 | CLI | `feat: añade el runner CLI de borradores con demostración del ciclo` |
| 13 | Helpers de test | `test: añade los handoffs de muestra para las pruebas de la Parte 2` |
| 14 | Tests generadores + evaluadores | `test: añade las pruebas de los generadores y evaluadores con un fallo de compliance del BRIEFING` |
| 15 | Tests grafo, runner y SQL | `test: añade las pruebas del ciclo generador-evaluador, el runner y el almacén SQL` |
| 16 | Tests rutas + contrato | `test: añade las pruebas del relanzamiento de borradores y actualiza el contrato de rutas` |
| 17 | CI | `ci: ejecuta las pruebas de la Parte 2 de RFPs` |
| 18 | Diseño | `docs: documenta la generación y evaluación de respuestas a RFPs` |
| 19 | `progress.md` | `docs: registra la Parte 2 de RFPs en progress` |

## 4. Verificación (Marisin, en el Codespace)

| # | Paso | Criterio |
|---|---|---|
| V1 | `services/sql/004_rfp_drafting.sql` en Supabase | 3 tablas: 20 / 18 / 20 columnas |
| V2 | `python -m pytest -q` | todo en verde (contrato de rutas 47) |
| V3 | Demo del ciclo sin BD (`--demo retry` y `--demo review`) | sección que falla y se corrige; sección que agota el límite |
| V4 | UI: «Generar borradores» en los tickets de ModaViva y Luna (o subir de nuevo) | estados en tiempo real; secciones evaluadas con el LLM |
| V5 | `--show` de cada ticket a `docs/rfp-drafting/evidence/` | JSON para el PR (una sección que pasa y una que falla) |

## 5. Registro

* 2026-11-23 — Plan e implementación preparados por Claude en un parche (`rfp-response-generation.patch`). Probado en el entorno de Claude: generadores y evaluadores con Python puro (31 tests); grafo, runner y demos con un doble local de LangGraph (13 tests); tipos de la página con `tsc` y tipos de React simulados. Sin LangGraph real, FastAPI ni SQLModel en ese entorno: grafo, rutas y almacén SQL los verifica Marisin (V2). Pendiente de Marisin: V1–V5.
