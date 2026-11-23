# Plan y registro — Flujo Agéntico de RFPs: Recepción y Enrutamiento · Parte 1 de 3 (TrackFlow)

> **Proyecto 4Geeks:** "Hito — Flujo Agéntico de RFPs: Recepción y Enrutamiento (Parte 1 de 3)".
> **Rama:** `feature/rfp-intake`, creada por Marisin **desde `feature/agent-guardrails`** (PRs #29–#33 pendientes de merge; `main` está en el PR #28).
> **Dependencias nuevas (las añade Marisin con `uv add`):** `markitdown[pdf]` y `py-readability-metrics`. El parche no toca `pyproject.toml` ni `uv.lock`.
> **BRIEFING:** `content/contexts/09-agentic-workflows/trackflow-BRIEFING.es.md` (resumido en `docs/rfp-intake/rfp-intake-design.md` §1).

## 0. Reglas
1. Un commit por acción, prefijo convencional y descripción en español.
2. Sin API nuevo: rutas en el backend existente (`services/rfp/`), grafo y agentes en `data/pipelines/rfp_intake/`, CLI en `scripts/`.
3. Grafo `rfp_intake` dedicado: nada del grafo de CX (`services/agent/`).
4. Ticket, metadatos y `key_aspects` en PostgreSQL (Supabase); nunca TinyDB ni JSON.
5. Departamentos, estados y muestras exactamente como el BRIEFING; nunca se inventan cifras.
6. No se edita ningún `.env*`: no hacen falta variables nuevas (reutiliza `LLM_*` y `DATABASE_URL`).

## 1. Rúbrica → dónde se cumple

| Criterio | Dónde |
|---|---|
| Solo el mismo backend API; pipeline en `data/pipelines/`; sin segundo servicio HTTP | `services/rfp/router.py` incluido en `services/api/main.py`; `data/pipelines/rfp_intake/`; `scripts/rfp_intake_run.py` es CLI |
| Ticket, metadatos y aspectos clave en PostgreSQL (Supabase) | `services/sql/003_rfp_intake.sql` + `data/pipelines/rfp_intake/sql_store.py` (SQLModel) |
| PDF subido por la UI → `data/raw/` | `uis/backoffice/src/app/rfp/page.tsx` → `POST /rfp/tickets` → `intake.accept_upload()` → `data/raw/rfp/<rfp_id>.pdf` |
| Estado real: `analizando` → `analisis_completo` / `descartado` | `runner.process_ticket()`; `stage = error` si falla (sigue `analizando`), `stale` si se detiene |
| Subida async (202 + background + estado consultable) | `BackgroundTasks`; `GET /rfp/tickets[/{id}]`; poll cada 3 s en la UI |
| El clasificador rechaza no-RFPs sin detener otros tickets | `classifier.py`; `process_ticket_safely`; `test_one_failed_ticket_does_not_stop_the_others` |
| Metadatos y legibilidad por documento | `metadata.py`, `metrics.py` (`py-readability-metrics` + fórmulas propias + Fernández Huerta) → `rfp_metadata` |
| Orchestrator-worker-synthesizer en grafo dedicado | `graph.py` (`Send` por departamento), `orchestrator.py`, `workers.py`, `synthesizer.py` |
| Handoff con `ticket_id` + payload del synthesizer | `rfp_tickets.handoff` (`trackflow.rfp_intake.handoff/v1`) + `ready_for_drafting` (cola); design §6 |
| Aspectos clave + contactos por departamento, verificable con las muestras | UI «Qué pedir a quién»; `handoff.departments[].ask/responsible/key_aspects/open_questions` |
| Tests del clasificador y ≥ 1 worker | `tests/pipelines/test_rfp_intake_classifier.py`, `test_rfp_intake_workers.py` (+ metadatos, orquestación, grafo, SQL, rutas) |
| Departamentos y formato del BRIEFING | `config.py` (ids, responsables, país → moneda, estados) |

## 2. Decisiones (D1–D10)

| # | Decisión | Por qué |
|---|---|---|
| D1 | Base `feature/agent-guardrails` (PR encadenado). | Los PRs #29–#33 no están en `main`; partir de `main` daría conflictos (contrato de rutas, conftest, CI). |
| D2 | `POST /rfp/tickets` recibe el PDF como cuerpo binario (`application/pdf`, `?filename=`). | Sin depender de `python-multipart`; el proxy `/api/backend` lo pasa tal cual. |
| D3 | `BackgroundTasks` de FastAPI para el pipeline. | Mismo proceso y sin segundo servicio; Celery queda como evolución (misma función). |
| D4 | Persistencia paso a paso desde el runner; nodos puros. | El ticket refleja la última etapa real; los nodos se prueban sin BD. |
| D5 | `stage` interno + `error_stage`/`error_message` + `stale`, sin estados nuevos. | El vocabulario de estados es el del BRIEFING; el fallo no se disfraza de éxito. |
| D6 | Cada agente: LLM con JSON validado + guardas + respaldo por reglas. | Mismo patrón del enrutador de CX; determinista en tests y robusto si el LLM cae. |
| D7 | Exclusión explícita de un servicio gana siempre (cláusula a cláusula). | ModaViva nunca debe activar `lastmile`. |
| D8 | Moneda y `departments_needed` por mapeo fijo, no por el LLM. | BRIEFING §5 y §2.1. |
| D9 | Guarda de cifras: todo número de un aspecto debe estar en extractos/metadatos. | «Nunca inventes volúmenes» (BRIEFING §2.3). |
| D10 | Handoff = campo `handoff` + bandera `ready_for_drafting` con índice parcial. | Contrato sin segundo API; la Parte 2 arranca sin re-parsear el PDF (Markdown en `rfp_tickets.markdown`). |

## 3. Commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan de la recepción y enrutamiento de RFPs` |
| 2 | Configuración, contratos y utilidades de texto | `feat: añade la configuración del BRIEFING y los contratos del flujo de RFPs` |
| 3 | Conversión y legibilidad | `feat: convierte las RFPs de PDF a Markdown y calcula su legibilidad` |
| 4 | Señales y clasificador | `feat: añade el agente clasificador de RFPs con respaldo por reglas` |
| 5 | Metadatos | `feat: añade el agente de metadatos de la RFP con guardas de anclaje` |
| 6 | Orquestador, workers y synthesizer | `feat: añade el orquestador, los workers por departamento y el synthesizer` |
| 7 | Grafo | `feat: añade el grafo dedicado rfp_intake con workers en paralelo` |
| 8 | Persistencia | `feat: persiste el ticket RFP, sus metadatos y los aspectos por departamento en PostgreSQL` |
| 9 | Recepción y runner | `feat: añade la recepción del PDF y el runner del pipeline de RFPs` |
| 10 | API | `feat: expone la recepción de RFPs en modo ticket en el backend` |
| 11 | UI | `feat: añade la página de recepción de RFPs al backoffice` |
| 12 | CLI | `feat: añade el runner CLI para reprocesar y exportar tickets de RFP` |
| 13 | conftest + fixtures | `test: añade las muestras del BRIEFING y aísla el LLM del flujo de RFPs` |
| 14 | Tests de agentes | `test: añade las pruebas del clasificador, los workers y los metadatos` |
| 15 | Tests de orquestación, grafo y SQL | `test: añade las pruebas del orquestador, el grafo y el almacén SQL` |
| 16 | Tests de rutas + contrato | `test: añade las pruebas de los endpoints de RFP y actualiza el contrato de rutas` |
| 17 | Diseño | `docs: documenta el flujo de recepción y enrutamiento de RFPs` |
| 18 | READMEs + gitignore + requirements | `docs: documenta el runner de RFPs y la carpeta data/raw/rfp` |
| 19 | CI | `ci: ejecuta las pruebas del flujo de RFPs` |
| 20 | `progress.md` | `docs: registra la recepción de RFPs en progress` |

## 4. Verificación (Marisin, en el Codespace)

| # | Paso | Criterio |
|---|---|---|
| V0 | `uv add 'markitdown[pdf]' py-readability-metrics` + descarga de `punkt` de NLTK | commit `chore:` propio |
| V1 | `services/sql/003_rfp_intake.sql` en Supabase | 3 tablas (18/18/16 columnas) |
| V2 | `python -m pytest -q` | todo en verde (contrato de rutas 46) |
| V3 | Smoke run CLI con un PDF de muestra | `analisis_completo` sin BD |
| V4 | API + backoffice: subir las 3 muestras por `/rfp` | formal e informal → `analisis_completo`; inválido → `descartado` |
| V5 | `--show` de cada ticket a `docs/rfp-intake/evidence/` | JSON del resultado para el PR |

## 5. Registro

* 2026-11-22 — Plan e implementación preparados por Claude en un parche (`rfp-intake.patch`). Probado en el entorno de Claude: conversión real de los 3 PDF con MarkItDown, clasificador, metadatos, orquestador, workers y synthesizer con Python puro (52 tests); grafo y runner con un doble local de LangGraph; SQL en PostgreSQL 16 local (idempotente, checks); tipos de la página con `tsc`. Sin FastAPI ni SQLModel en ese entorno: rutas y almacén SQL los verifica Marisin (V2). Pendiente de Marisin: V0–V5.
* 2026-11-23 — En el Codespace (con el Claude del Codespace aplicando los parches): conflicto de `git am` en `progress.md` resuelto a mano (entró un commit nuevo en `feature/agent-guardrails`). Dos fallos reales corregidos con `fix:`: el LLM no llegaba a los nodos porque LangGraph no reconocía la anotación de `config` (ahora `build_graph(llm)` fija el LLM en cada nodo) y `py-readability-metrics` inflaba Flesch-Kincaid en español (la densidad en español la decide Fernández Huerta). Suite: 705 passed. SQL en Supabase (16/18/18). Prueba real por la UI con el LLM de 4Geeks: ModaViva y Luna → `analisis_completo` con los departamentos correctos; RapidShip → `descartado`. Evidencias en `docs/rfp-intake/evidence/`.

