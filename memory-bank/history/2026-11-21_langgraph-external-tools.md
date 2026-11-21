# Plan y registro — Agente de Soporte con LangGraph · Parte 2 de 2: Herramientas fuera del RAG (TrackFlow)

> **Proyecto 4Geeks:** "Agente de Soporte con LangGraph — Parte 2 de 2: Herramientas Fuera del RAG".
> **Rama:** `feature/langgraph-external-tools`, creada **desde `feature/langgraph-agent-base`** (`b09e2ed`, PR #29 pendiente de revisión).
> **Ejecución:** sin agente. Claude implementa y entrega un parche (`git am`); Marisin ejecuta pytest, arranca la API, graba los traces reales, hace push y abre el PR con la etiqueta `langgraph-external-tools`.
> **Decisiones de Marisin (2026-11-21):** enrutador **híbrido LLM + reglas** e **incluir la tool extra de inventario**.

## 0. Reglas

1. Un commit por acción, con prefijo convencional y descripción en español. El parche no toca `pyproject.toml` ni `uv.lock` (no hay dependencias nuevas: `httpx` ya está).
2. Las tools leen de los servicios reales ya construidos, por HTTP. Prohibido simular datos o crear un dataset paralelo.
3. Las tools son de solo lectura: solo `GET`. Hay un test que falla si se usa otro método.
4. El RAG de la Parte 1 se reutiliza tal cual (`retrieve()` y `generate_answer()` por separado; nunca `query()`).
5. El agente nunca toca el fichero TinyDB donde viven los incidentes (excluido por política): lo consulta por la API.

## 1. Rúbrica

| Criterio | Dónde se cumple |
|---|---|
| Contrato tipado de entrada/salida; lee del gestor de incidentes real | `TicketQuery` → `TicketRecord` / `ToolResult` en `services/agent/tools.py`; `GET /api/incidents[/{id}]` por HTTP |
| Auth | Los `GET` de incidentes e inventario **no tienen auth** (se indica en el PR). Si se protegen: `AGENT_BACKEND_TOKEN` del entorno → `Authorization: Bearer` |
| Solo lectura | Único punto de salida `http_get_json()` (GET); test que lo verifica |
| Timeout numérico | `TOOL_TIMEOUT_SECONDS = 4.0` (httpx); test de timeout |
| Fallback verificable | `ToolResult.status` `not_found` / `unavailable` → nodo `tool_fallback` → respuesta honesta; evals E10/E11 |
| Enrutamiento automático | Nodo `route_question` (LLM + guardas + reglas); evals E7/E8/E9 |
| Una responsabilidad por tool | `lookup_tickets` (incidentes) y `lookup_inventory` (inventario), en nodos distintos |
| Trace con fuentes y orden | `trace["sources"]` (p. ej. `["incidents", "rag"]`), `trace["route"]` y el orden de nodos en `path` |
| ≥ 2 evals nuevos de enrutamiento | E7–E12 en `tests/pipelines/test_agent_evals.py` |
| (Extra) Inventario con las mismas reglas | `InventoryQuery` → `ProductStock`; mismo timeout y fallback |

## 2. Decisiones (T1–T12)

| # | Decisión | Por qué |
|---|---|---|
| T1 | Transporte **HTTP** con `httpx` a `AGENT_BACKEND_URL` (por defecto `http://localhost:8000`). | Dato siempre actual; timeout y "servicio caído" reales; el agente no toca el TinyDB. |
| T2 | Endpoints sin auth → no se envía token; `AGENT_BACKEND_TOKEN` opcional desde el entorno. | La rúbrica pide no hardcodear credenciales e indicar la ausencia de auth. |
| T3 | Timeout de **4 s** por llamada. | Dentro del rango 3–5 s del enunciado. |
| T4 | Las tools **no lanzan**: devuelven `ok` / `not_found` / `unavailable`. | El grafo decide la ruta de recuperación; un fallo nunca rompe la corrida. |
| T5 | Enrutador híbrido: LLM con salida JSON validada contra `RouteDecision` → **guardas de anclaje** (id/SKU/producto deben aparecer en la pregunta) → reglas de respaldo. | El agente decide solo y nunca consulta un recurso inventado; si el LLM falla, decide por reglas. |
| T6 | Orden de fuentes: tickets → inventario → RAG → `compose_answer`. | Determinista y legible en el trace. |
| T7 | La parte de la respuesta que viene de una tool se escribe **con plantilla**, sin LLM. | Un estado o un stock nunca se pueden inventar. |
| T8 | Nodo `tool_fallback` explícito tras cualquier tool con `not_found`/`unavailable`. | Ruta de recuperación visible en el trace. |
| T9 | Estado: se añaden `route`, `ticket_result`, `inventory_result` y `rag_answer`. Sigue sin historial. | Cada clave la leen los routers o `compose_answer`. |
| T10 | Respuesta de la API: `{run_id, status, answer, sources}`; nuevo `status = tool_fallback`. | El cliente ve qué fuentes se usaron. |
| T11 | Evals sobre traces grabados; el grabador **elige un ticket y un SKU reales** de la API y fuerza "servicio caído" con un puerto cerrado. | Sin ids inventados, criterios verificables. |
| T12 | Se actualizan las rutas esperadas de los evals de la Parte 1 (nuevos nodos `route_question` y `compose_answer`) y se vuelven a grabar. | El grafo cambió; los evals deben reflejarlo. |

## 3. Grafo

```
START → receive_question ─empty→ invalid_question → END
                         └valid→ route_question → [lookup_ticket] → [lookup_inventory] → [retrieve → generate_answer | no_context] → compose_answer → END
                                                  (tool con not_found/unavailable → tool_fallback → siguiente fuente)
```

## 4. Acciones y commits

| # | Acción | Commit |
|---|---|---|
| 1 | Este plan | `docs: añade el plan de las tools externas del agente` |
| 2 | `services/agent/tools.py` | `feat: añade las tools de incidentes e inventario con contrato tipado y timeout` |
| 3 | `services/agent/routing.py` | `feat: añade el enrutador híbrido LLM + reglas del agente` |
| 4 | `services/agent/answers.py` | `feat: redacta con plantilla las respuestas de las tools y el fallback` |
| 5 | `state.py`, `nodes.py`, `graph.py` | `feat: amplía el grafo con enrutamiento, tools y fallback` |
| 6 | `runner.py`, `tracing.py`, `schemas.py`, `router.py` | `feat: registra las fuentes usadas en el trace y en la respuesta` |
| 7 | `.env.example` | `chore: documenta la URL del backend para las tools del agente` |
| 8 | `tests/pipelines/test_agent_tools.py`, `test_agent_routing.py` | `test: añade pruebas de las tools y del enrutador` |
| 9 | `tests/pipelines/test_agent_graph.py`, `tests/test_agent_routes.py` | `test: adapta las pruebas del grafo y del endpoint a la Parte 2` |
| 10 | casos de eval + `scripts/agent_record_traces.py` | `feat: amplía los casos de eval y el grabador de traces con las tools` |
| 11 | `tests/pipelines/test_agent_evals.py` | `test: añade los evals de enrutamiento y fallback` |
| 12 | CI | `ci: ejecuta las pruebas de las tools y del enrutador` |
| 13 | `docs/agent/agent-tools-design.md` | `docs: añade el diseño de las tools externas del agente` |
| 14 | `memory-bank/progress.md` | `docs: registra las tools externas del agente en progress` |
| 15 | **Marisin:** grabar traces y evidencias | `test: graba los traces reales de los evals de la Parte 2` |

## 5. Verificación (Marisin)

1. `python -m pytest -q --ignore=tests/pipelines/test_agent_evals.py` en verde.
2. API arriba (`uvicorn`) con al menos un incidente y Qdrant → `python scripts/agent_record_traces.py`.
3. `python -m pytest tests/pipelines/test_agent_evals.py -v | tee docs/agent/tools-eval-results.txt`.
4. Evidencia del PR: trace con la tool de tickets, trace con el RAG y salida de los evals.

## 6. Registro

- 2026-11-21 — Plan y parche preparados por Claude. Sin `langgraph` ni `httpx` en el entorno de Claude: la lógica de tools, enrutador, nodos y composición se probó en local con un motor que reproduce el grafo y con la capa HTTP sustituida; los tests que importan `langgraph`/`httpx` se ejecutan en el Codespace.
