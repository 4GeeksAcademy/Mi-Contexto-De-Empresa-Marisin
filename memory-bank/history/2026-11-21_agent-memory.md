# Plan y registro — Memoria y Auto-mejora de Agentes · Parte 1 (TrackFlow)

> **Proyecto 4Geeks:** "Hito — Memoria y Auto-mejora de Agentes (Parte 1 de 2)". **Ticket #MEM-092.**
> **Rama:** `feature/agent-memory`, creada por Marisin **desde `feature/mcp-oauth-tools`** (PR #29, #30 y el del MCP pendientes de merge): el proyecto extiende el agente que ya consume el servidor MCP.
> **Dependencias:** ninguna nueva. `redis` ya está en `pyproject.toml` (Celery). El parche no toca `pyproject.toml` ni `uv.lock`.
> **BRIEFING:** `content/contexts/08-agent-engineering/memory/trackflow-BRIEFING.es.md` del syllabus (copiado en `docs/agent-memory/memory-design.md` §2).

## 0. Reglas
1. Un commit por acción, con prefijo convencional y descripción en español.
2. Es el **mismo** agente LangGraph: sin grafo nuevo ni multi-agente. La auto-evaluación es un campo más de la salida estructurada que ya existía.
3. La memoria nunca escribe en `trackflow_knowledge` (Qdrant): el RAG sigue siendo de solo lectura.
4. Ninguna escritura sin una decisión explícita del usuario, clasificada (no `"sí" in mensaje`). Silencio o ambigüedad = descarte.
5. Lo prohibido por el BRIEFING lo bloquea código determinista, para B2C **y** B2B.
6. Sin pendiente ni propuesta, la ruta del grafo es la de la Parte 2: los traces grabados de los evals no se regraban.
7. No se edita ningún `.env*`.

## 1. Rúbrica → dónde se cumple

| Criterio | Dónde |
|---|---|
| Arquitectura justificada por escrito | `docs/agent-memory/memory-design.md` §3 |
| Nunca escribe en `*_knowledge` | Redis bajo `trackflow:agent_memory:`; `check_prefix()` + test |
| Interfaz explícita de lectura/escritura | `services/agent/memory/store.py` (`MemoryStore`) |
| Distingue memorables (≥3) y no memorables (≥3) | `data/eval/agent-memory-cases.json` (3 + 4 + 4 prohibidos) · design §4 · `evidence/self-eval.json` |
| Propuesta en la misma conversación | `propose_memory` añade la pregunta al final de la respuesta |
| Ninguna escritura sin decisión clasificada | `memory/decision.py` (LLM + guardas + reglas de frase completa) |
| Una pendiente a la vez; silencio/ambigüedad = rechazo | `SET NX` por conversación · `discarded_*` · `expired` |
| Registro auditable de todo | Redis Stream `audit` · `GET /agent/memory/audit` |
| Consolidación/limpieza documentada y funcional | `MemoryStore.consolidate_fact` / `consolidate` · `scripts/agent_memory_consolidate.py` · design §7 |
| Dos ciclos de evidencia (aprobado y rechazado) | `scripts/agent_memory_evidence.py` → `docs/agent-memory/evidence/` (+ ciclo de cambio de tema) |
| Decisiones según el BRIEFING | design §2, §6 y §8 |

## 2. Decisiones (D1–D12)

| # | Decisión | Por qué |
|---|---|---|
| D1 | Memoria episódica curada en **Redis** (JSON por clave + Stream de auditoría). | Pocos hechos con ámbito exacto, TTL nativo, `SET NX`, log append-only; Redis ya está en el stack (Celery, AOF). |
| D2 | Tres categorías del BRIEFING: `carrier_rule`, `known_incident`, `b2b_report_preference`. | Lo único memorable para TrackFlow. |
| D3 | Slots: carrier + país (zona como clave), zona + país, cliente. | Consolidación sugerida por el BRIEFING. |
| D4 | `memory_proposal` en la salida JSON del **enrutador LLM**. | Es la única llamada estructurada presente en todos los caminos (tools con plantilla y `no_context` sin LLM por diseño): una sola llamada, sin segundo agente. |
| D5 | Política determinista sobre la propuesta **y** el mensaje de origen. | El LLM no tiene la última palabra; cubre B2C y B2B. |
| D6 | Clasificador de la decisión con LLM (etiqueta + confianza ≥ 0,75 + guardas) y reglas de frase completa como respaldo. | Clasificación explícita; fail-closed. |
| D7 | `edit` = aprobar con el texto del usuario, tras volver a pasar la política. | El usuario autoriza explícitamente el contenido corregido. |
| D8 | Pendiente: 1 por conversación, 30 min; solo decide quien la recibió. | Una a la vez; nunca aprobación por silencio. |
| D9 | Caducidad 7 / 90 / 180 días, 5 hechos por slot, 100 slots por categoría. | Memoria acotada y que olvida. |
| D10 | Sustituir una regla de otra persona exige `admin`/`manager`; 10 aprobaciones por usuario y día. | Anti-envenenamiento. |
| D11 | Notas con plantilla al final de la respuesta, fuera del prompt del LLM y separadas de la base documental. | No inventan, no inyectan, no se confunden con el RAG. |
| D12 | Memoria activa solo con usuario (`POST /agent/query`); sin usuario (scripts de evals), el grafo es el de la Parte 2. | Los 55 evals grabados siguen válidos. |

## 3. Commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan de la memoria del agente` |
| 2 | `memory/__init__.py`, `models.py`, `policy.py` | `feat: añade los contratos y la política de memoria del BRIEFING` |
| 3 | `backend.py`, `store.py` | `feat: añade el almacén de memoria en Redis con consolidación, limpieza y auditoría` |
| 4 | `decision.py` | `feat: añade el clasificador de la decisión sobre la propuesta de memoria` |
| 5 | `flow.py` | `feat: añade el ciclo propuesta, decisión y consolidación de la memoria` |
| 6 | `routing.py` | `feat: añade la auto-evaluación de memoria a la salida estructurada del enrutador` |
| 7 | `state.py`, `nodes.py`, `graph.py`, `tracing.py`, `runner.py` | `feat: integra la memoria en el grafo del agente` |
| 8 | `schemas.py`, `router.py` | `feat: expone la conversación, la memoria y su auditoría en la API del agente` |
| 9 | `tests/conftest.py` | `test: aísla la memoria del agente en un almacén en memoria` |
| 10 | Tests de política, almacén y decisión | `test: añade las pruebas de política, almacén y decisión de la memoria` |
| 11 | Ciclos por grafo/API y pruebas adaptadas (rutas 40 → 42) | `test: añade los ciclos de memoria por el grafo y la API` |
| 12 | Prueba contra Redis real | `test: añade la prueba de la memoria contra Redis` |
| 13 | Casos + script de evidencias | `feat: añade los casos de auto-evaluación y el script de evidencias de la memoria` |
| 14 | Script de limpieza | `feat: añade el script de limpieza de la memoria del agente` |
| 15 | Diseño | `docs: documenta la arquitectura de memoria del agente` |
| 16 | `scripts/README*.md` | `docs: documenta los scripts de la memoria del agente` |
| 17 | CI | `ci: ejecuta las pruebas de la memoria del agente` |
| 18 | `progress.md` | `docs: registra la memoria del agente en progress` |

## 4. Verificación (Marisin, en el Codespace)

| # | Paso | Criterio |
|---|---|---|
| V1 | `python -m pytest -q` | Todo en verde (los evals grabados incluidos). |
| V2 | `docker compose up -d redis qdrant` + `python -m pytest tests/pipelines/test_agent_memory_redis.py -v` | 1 passed (no skipped). |
| V3 | `python scripts/agent_memory_evidence.py` | `self-eval` OK y los tres ciclos OK; ficheros en `docs/agent-memory/evidence/`. |
| V4 | API: `POST /agent/query` con el mensaje de SEUR → `sí, recuérdalo` con el `conversation_id` → pregunta nueva; `GET /agent/memory` y `/agent/memory/audit` como admin. | Capturas para el PR. |
| V5 | `python scripts/agent_memory_consolidate.py --show` | Informe JSON de la limpieza. |

## 5. Registro

* 2026-11-21 — Plan e implementación preparados por Claude en un parche (`agent-memory.patch`). Probados en el entorno de Claude: política, almacén y decisión (71 tests) con Python puro; grafo, enrutador y evals con un doble local de LangGraph (sin FastAPI ni Redis allí). Pendiente de Marisin: V1–V5.
