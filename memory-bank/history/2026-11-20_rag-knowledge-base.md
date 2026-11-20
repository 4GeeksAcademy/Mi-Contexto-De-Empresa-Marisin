# Plan y registro — Hito 7: RAG y Base de Conocimiento (TrackFlow)

> **Proyecto 4Geeks:** "Hito — RAG y Base de Conocimiento". Es el último de la serie, tras la predicción de ventas (#26) y la evaluación del modelo (#27).
> **Monorepo:** `Mi-Contexto-De-Empresa-Marisin` (TrackFlow).
> **Rama:** `feature/rag-knowledge-base`, creada por Marisin **desde `feature/regression-model-eval`** (`b19d891`, PR #27 pendiente) para evitar conflictos en `progress.md`, `data/eval/README*` y el workflow de CI. Cadena: `main ← #26 ← #27 ← esta`.
> **Ejecución:** sin agente. Claude implementa y entrega parches (`git am`). Marisin añade las dependencias con `uv add`, rellena `.env` a mano, levanta Qdrant, ejecuta `setup()`, la eval, pytest, typecheck y build, y hace push y el PR.
> **Fuente de verdad:** `trackflow-BRIEFING.es.md` de `content/contexts/07-trainning-rag/` y los documentos de `content/contexts/00-general-contexts/trackflow/` (syllabus de 4Geeks).

## 0. Reglas

1. Un commit por acción, con prefijo convencional y descripción en español.
2. El parche no toca `pyproject.toml` ni `uv.lock`: Marisin ejecuta `uv add qdrant-client openai`.
3. Las claves solo van en `.env`, nunca en el código ni en el repo. `.env.example` lleva los nombres de las variables vacíos.
4. Valores del BRIEFING literales: colección `trackflow_knowledge`, payload `company` / `source_document` / `section` / `language` / `chunk_index` / `text`, enum de `source_document`, Recall@3 ≥ 80 %, ≥ 3 chunks por documento y ≥ 8 preguntas de prueba.

## 1. Decisiones (R1–R12)

| # | Decisión | Por qué |
|---|---|---|
| R1 | Corpus: los 4 `.es.md` copiados sin cambios a `docs/company-knowledge-base/`. | BRIEFING §2; `language = "es"`. |
| R2 | Chunking por párrafo o lista completa; la intro que termina en `:` viaja con su bloque; sección = título + etiqueta "X:". | Ninguna regla separada de su condición; 14 chunks (3/5/3/3). |
| R3 | `text` = sección + cuerpo, y es lo que se embebe y lo que llega al prompt. | Chunks autocontenidos y trazables. |
| R4 | IDs uuid5 deterministas + `upsert` + borrado de huérfanos; se recrea la colección si cambia la dimensión. | `setup()` idempotente (BRIEFING Fase 1). |
| R5 | SDK `openai` contra la URL OpenAI-compatible de 4Geeks; `EMBEDDING_MODEL` ≠ `LLM_MODEL`, comprobado con `check_models()`. | Dos modelos, dos trabajos. |
| R6 | `retrieve(query, *, k=5, min_score)` devuelve payloads ≥ umbral; puede devolver menos de k o ninguno. | Rúbrica Fase 2. |
| R7 | `generate_answer(question, context)` separada; `query()` = `retrieve()` + `generate_answer()`. | Reutilización por el agente LangGraph. |
| R8 | Prompt con voz de vendedor de TrackFlow y las restricciones del BRIEFING §6 (Black Friday/Rebajas, devoluciones internacionales manuales, descuentos con Miguel Torres, excepciones con Carlos Vega); línea `Fuente:`. | Voz/audiencia y trazabilidad. |
| R9 | Sin contexto → el LLM recibe `SIN CONTEXTO RELEVANTE` y dice que no hay información suficiente. | La respuesta siempre la genera el modelo, sin inventar. |
| R10 | `POST /knowledge/query` en `services/knowledge/`, con sesión, que solo devuelve `{answer}`; 503 si falla el pipeline. | El router reutiliza `query()` sin duplicar lógica. |
| R11 | UI en `/knowledge` del backoffice con estados de carga y error, modo oscuro (`dark:`) y preguntas de ejemplo. | Fase 4. |
| R12 | Eval: 16 preguntas + 4 fuera de alcance; `scripts/rag_eval.py` mide Recall@3, sugiere `min_score` y comprueba la fidelidad de cifras. | Fase 5b y KPIs §4. |

## 2. Acciones y commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan del hito RAG y base de conocimiento` |
| 2 | `docs/company-knowledge-base/` | `docs: añade los documentos fuente de la base de conocimiento de TrackFlow` |
| 3 | `docker-compose.yml`, `.env.example`, `services/requirements.txt` | `chore: añade Qdrant y la configuración de modelos del RAG` |
| 4 | `data/process/rag.py` + READMEs | `feat: añade el chunking semántico, embed y setup del RAG` |
| 5 | `data/pipelines/rag.py` + READMEs | `feat: añade retrieve, generate_answer y query del RAG` |
| 6 | `services/knowledge/`, `main.py` y conteo de rutas | `feat: expone POST /knowledge/query` |
| 7 | Backoffice `/knowledge` + menú | `feat: añade la página del asistente comercial al backoffice` |
| 8 | `tests/pipelines/test_rag.py`, `tests/test_knowledge_routes.py`, CI | `test: añade pruebas unitarias del RAG y del endpoint` |
| 9 | `data/eval/test-queries.json`, `scripts/rag_eval.py` + READMEs | `feat: añade la eval de retrieval del RAG (Recall@3)` |
| 10 | `docs/rag/rag-design.md` | `docs: añade el documento de diseño del RAG` |
| 11 | `memory-bank/progress.md` | `docs: registra el hito RAG en progress` |
| 12 | **Marisin:** `uv add qdrant-client openai` | `chore: añade qdrant-client y openai` |
| 13 | Resultados reales: `min_score`, `rag_eval_results.json`, cifras de `rag-design.md` | segundo parche, tras ejecutar la eval |

## 3. Registro

- 2026-11-20 — Primer parche (acciones 1-11) preparado por Claude. Probado en local con un Qdrant simulado y un embedding léxico de prueba: 14 chunks y Recall@3 del 100 %. La cifra válida es la del modelo real de 4Geeks.
- 2026-11-20 — Marisin generó la clave `trackflow-rag` en 4geeks.com (Recursos → Claves API para LLM). El gateway `https://llm.4geeks.ai` expone los modelos **sin** el prefijo `litellm/` que muestra la web, que provocaba un 403. Se usan `madrid-spain/openrouter/perplexity/pplx-embed-v1-0.6b` (embeddings, dimensión 1024) y `madrid-spain/opnerouter/openai/gpt-6-luna` (generación).
- 2026-11-20 — `setup()`: 14 chunks en `trackflow_knowledge`. Eval: **Recall@3 = 100 %** (16/16 en el puesto 1); chunk correcto ≥ 0,539 y fuera de alcance ≤ 0,383 → `min_score = 0,46`. Fidelidad: solo se marcó la q15 por el "60" de la pregunta; se corrige `unsupported_figures()` para contar los números de la pregunta. Qdrant pasa a v1.20.0, la misma versión menor que el cliente.
