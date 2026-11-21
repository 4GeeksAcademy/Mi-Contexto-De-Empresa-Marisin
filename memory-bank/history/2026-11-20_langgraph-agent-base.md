# Plan y registro — Agente de Soporte con LangGraph · Parte 1 de 2 (TrackFlow)

> **Proyecto 4Geeks:** "Agente de Soporte con LangGraph — Parte 1 de 2: Migración y Flujo del Agente".
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Rama:** `feature/langgraph-agent-base`, creada por Marisin **desde `feature/rag-knowledge-base`** (`be741b9`, PR #28 pendiente). Cadena: `main ← #26 ← #27 ← #28 ← esta`.
> **Ejecución:** sin agente. Claude implementa y entrega parches (`git am`). Marisin añadió `langgraph` 1.2.24 (`langgraph-checkpoint` 4.3.2) con `uv add` (commit `chore: añade langgraph`), ejecuta pytest, graba los traces con el modelo real, hace push y abre el PR.
> **Fuente de verdad:** el enunciado del proyecto y la base de conocimiento del Hito 7 (`docs/company-knowledge-base/`, BRIEFING `07-trainning-rag`). No hay BRIEFING específico de LangGraph en el syllabus.

## 0. Reglas

1. Un commit por acción, con prefijo convencional y descripción en español.
2. El parche no toca `pyproject.toml` ni `uv.lock`.
3. **No se reescribe el RAG:** los nodos importan `retrieve()`, `generate_answer()` y `unsupported_figures()` de `data/pipelines/rag.py`. Ningún nodo llama a `query()` (hay un test que lo prohíbe).
4. `POST /knowledge/query` y sus tests no cambian: el agente **convive** con el endpoint RAG.
5. Los evals leen traces grabados; no ejecutan el grafo en vivo.

## 1. Rúbrica (resumen)

| Criterio | Dónde se cumple |
|---|---|
| Estado mínimo y explícito | `services/agent/state.py` (4 claves, sin historial) |
| Nodos de responsabilidad única | `services/agent/nodes.py` |
| Aristas por condiciones de salida | `route_after_receive`, `route_after_retrieve` + `GraphSpec` en `graph.py` |
| Compilación explícita con error claro | `compile_graph()` + `validate_structure()` → `GraphStructureError` |
| Checkpointing verificable | `InMemorySaver`; `checkpoints` en cada trace; test de reanudación |
| Trace consultable | `data/agent_traces/<run_id>.json` + `GET /agent/traces/{run_id}` |
| ≥ 3 evals en `tests/pipelines/`, uno de anclaje | `tests/pipelines/test_agent_evals.py` sobre `tests/pipelines/fixtures/agent_traces/` |
| Tests RAG siguen pasando | `test_rag.py` y `test_knowledge_routes.py` sin cambios |
| Endpoint sin lógica de negocio y sin stack traces | `services/agent/router.py` → `run_agent()`; 503/422 con mensaje claro |
| `retrieve` y generación por separado | nodos `retrieve` y `generate_answer` |
| Reutilización desde `data/pipelines/` | `from data.pipelines import rag as rag_pipeline` |

## 2. Decisiones (L1–L12)

| # | Decisión | Por qué |
|---|---|---|
| L1 | Rama desde `feature/rag-knowledge-base`. | El RAG (PR #28) aún no está en `main`. |
| L2 | Estado `AgentState` (`TypedDict`): `question`, `context`, `answer`, `status`. Sin historial de conversación. | Cada consulta es independiente; el historial llegará con la memoria (Hito 8) si se justifica. |
| L3 | Cinco nodos: `receive_question`, `retrieve`, `generate_answer`, `no_context`, `invalid_question`. | Una responsabilidad por nodo; nombres legibles en el trace. |
| L4 | Dos aristas condicionales: pregunta vacía → `invalid_question`; `retrieve` sin chunks ≥ `min_score` → `no_context`. | Rúbrica: al menos una condición real; no forzar la generación sobre contexto vacío. |
| L5 | `no_context` responde con un texto fijo y honesto, **sin llamar al LLM**. | Determinista, sin coste y sin riesgo de inventar. |
| L6 | El grafo se declara como datos (`GraphSpec`) y `validate_structure()` lo valida antes de `StateGraph.compile()`. | `compile()` de LangGraph 1.2 detecta aristas a nodos desconocidos, pero **no** nodos inalcanzables ni callejones sin salida. |
| L7 | El grafo se compila al importar `services/agent/graph.py` (`AGENT_GRAPH`). | Un error estructural rompe el arranque de la API, no una petición en producción. |
| L8 | Checkpointer `InMemorySaver` (incluido en `langgraph`), `thread_id = run_id`. | Sin dependencias nuevas. En producción: un saver persistente (Postgres). |
| L9 | Trace propio en JSON por corrida (nodo, orden, entrada resumida, salida, duración, error) + resumen de checkpoints. Sin LangSmith. | No hay clave de LangSmith; el trace queda consultable en disco y por API. |
| L10 | `POST /agent/query` devuelve `{run_id, status, answer}`; 422 si la pregunta está vacía (mensaje del grafo); 503 con referencia `run_id` si falla un nodo. `GET /agent/traces/{run_id}` solo para `admin`/`manager`. | El trace contiene chunks: no se expone a cualquier usuario (coherente con el Hito 7). |
| L11 | El schema del agente no exige `min_length`. | Si no, la rama "pregunta vacía" del grafo nunca se ejecutaría desde la API. |
| L12 | Evals: `data/eval/agent-eval-cases.json` → `scripts/agent_record_traces.py` graba los traces con el modelo real → `tests/pipelines/test_agent_evals.py` los evalúa. | Los evals corren contra el trace y con un solo comando. |

## 3. Ficheros autorizados

`services/agent/**`, `services/api/main.py` (registro del router), `services/requirements.txt`, `tests/pipelines/test_agent_graph.py`, `tests/pipelines/test_agent_evals.py`, `tests/pipelines/fixtures/agent_traces/`, `tests/test_agent_routes.py`, `tests/test_serialization_contracts.py` (conteo de rutas 38 → 40), `data/eval/agent-eval-cases.json`, `scripts/agent_record_traces.py` + READMEs, `docs/agent/`, `.gitignore`, `.github/workflows/sales-model-tests.yml`, `memory-bank/progress.md` y este plan.

## 4. Acciones y commits

| # | Acción | Commit |
|---|---|---|
| 0 | **Marisin:** `uv add langgraph` | `chore: añade langgraph` |
| 1 | Este plan | `docs: añade el plan del agente de soporte con LangGraph` |
| 2 | `.gitignore` + `services/requirements.txt` | `chore: ignora los traces del agente y añade langgraph al contenedor` |
| 3 | `services/agent/state.py` + `nodes.py` | `feat: define el estado y los nodos del agente de soporte` |
| 4 | `services/agent/structure.py` + `graph.py` + `tracing.py` (`graph.py` importa `traced`) | `feat: compila el grafo del agente con validación estructural` |
| 5 | `services/agent/runner.py` | `feat: traza cada corrida del agente con sus checkpoints` |
| 6 | `services/agent/schemas.py` + `router.py`, `main.py`, conteo de rutas | `feat: expone POST /agent/query y GET /agent/traces/{run_id}` |
| 7 | `tests/pipelines/test_agent_graph.py`, `tests/test_agent_routes.py` | `test: añade pruebas del grafo y del endpoint del agente` |
| 8 | `data/eval/agent-eval-cases.json`, `scripts/agent_record_traces.py` + READMEs | `feat: añade los casos de eval y el grabador de traces del agente` |
| 9 | `tests/pipelines/test_agent_evals.py` | `test: añade los evals del agente sobre traces grabados` |
| 10 | CI | `ci: ejecuta los tests y evals del agente` |
| 11 | `docs/agent/agent-design.md` | `docs: añade el diseño del agente LangGraph` |
| 12 | `memory-bank/progress.md` | `docs: registra el agente LangGraph en progress` |
| 13 | **Marisin:** grabar traces, guardar la salida de los evals | `test: graba los traces reales de los evals del agente` |

## 5. Verificación (Marisin)

1. `python -m pytest -q` → todo verde salvo `test_agent_evals.py`, que falla con un mensaje claro mientras no haya traces grabados.
2. Qdrant arriba y `.env` del Hito 7 → `python scripts/agent_record_traces.py`.
3. `python -m pytest tests/pipelines -v | tee docs/agent/eval-results.txt`.
4. `uvicorn` + `POST /agent/query` y `GET /agent/traces/{run_id}` (evidencia para el PR).

## 6. Registro

- 2026-11-20 — Plan y primer parche (acciones 1-12) preparados por Claude. LangGraph no se puede instalar en el entorno de Claude: la API se verificó leyendo el código fuente de `langgraph` 1.2.24 / `langgraph-checkpoint` 4.3.2. La validación estructural y los nodos se probaron en local; los tests que importan `langgraph` se ejecutan en el Codespace.
- 2026-11-20 — Verificación de Marisin en el Codespace: `python -m pytest -q --ignore=tests/pipelines/test_agent_evals.py` → **270 passed** a la primera (incluidos `test_rag.py`, `test_knowledge_routes.py` y el contrato de 40 rutas). Traces grabados con Qdrant y los modelos reales (`scripts/agent_record_traces.py`): a01–a04 `answered` (30 días · 40% · gestión manual de Sofía Ramos · 16 EUR por m³), a05 `no_context` y a06 `invalid`. Evals: **22 passed** (`docs/agent/eval-results.txt`).
- 2026-11-20 — Evidencia del endpoint con la API en marcha: `POST /agent/query` → `answered` con "30 días" y `Fuente: Política de Devoluciones`; `GET /agent/traces/{run_id}` devuelve el recorrido `receive_question → retrieve → generate_answer`; pregunta en blanco → `HTTP 422` con el mensaje de `invalid_question`. Ficheros en `docs/agent/evidence-*` y `endpoint-evidence.png`.

