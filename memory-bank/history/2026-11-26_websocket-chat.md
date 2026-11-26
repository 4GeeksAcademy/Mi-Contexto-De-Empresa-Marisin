# Plan — Sistemas en Tiempo Real: Streaming de Chat por WebSocket (Parte 2 de 2)

- **Rama:** `feature/websocket-chat`, creada por Marisin desde `feature/sse-notifications` (PR #37 sin mergear → PR encadenado, base `feature/sse-notifications`; cadena #34 → #35 → #36 → #37 → este).
- **Etiqueta del PR:** `websocket-chat`.
- **Fuente de verdad:** este plan + el enunciado. El BRIEFING de la Parte 2 (`trackflow-BRIEFING.es.md` en la raíz, sustituye al de la Parte 1 con el mismo nombre) es **solo de apoyo**: se lee una vez en la Fase 0 y **nunca se commitea** (excluido en local con `.git/info/exclude`). Lo que hace falta está copiado abajo.
- **Sin dependencias nuevas:** FastAPI/Starlette ya traen WebSocket; uvicorn 0.52.4 sirve WS con `websockets` 16.1.1, que ya está instalado como dependencia transitiva (langgraph-sdk, langsmith, prefect). Se comprueba en la Fase 0.
- **El agente no se rediseña:** mismo grafo, mismos nodos, mismas tools, misma memoria y mismo harness. Solo cambia el canal: la llamada al LLM de `generate_answer` gana una variante en streaming y `run_agent` gana un modo con tokens y cancelación. Sin `on_token`, el comportamiento es idéntico al de hoy (`POST /agent/query` y los evals no cambian).

---

## §0 Reglas para el agente (Claude Code del Codespace)

1. Git solo en local: prohibido `git pull`, `fetch`, `merge`, `rebase`, `push`, cambiar de rama y abrir el PR. Marisin hace push.
2. **Un commit por acción** (tabla de cada fase), prefijo convencional + descripción en español. Prohibido `git add .` / `-A`: rutas explícitas y `git status` antes de cada commit.
3. `trackflow-BRIEFING.es.md` es solo de lectura: nunca lo añadas a git, lo muevas, lo copies ni lo cites por ruta en código o docs.
4. Prohibido leer o editar cualquier `.env*`, el JSON local de TinyDB de proveedores y `node_modules/next/dist/docs`. Si alguno aparece en `git status`, para.
5. No instalar dependencias ni tocar `pyproject.toml`, `uv.lock`, `package.json` ni `package-lock.json`.
6. Puedes ejecutar `pytest` y `npm run typecheck`. **`uvicorn`, `npm run dev`, `npm run build` y `npm run start` los ejecuta Marisin**: prepara el comando y para.
7. Tras `npm run typecheck`: `git restore uis/backoffice/tsconfig.tsbuildinfo`. Tras `npm run dev`: `git restore uis/backoffice/next-env.d.ts`. Nunca commitearlos.
8. Una fase cada vez. Al terminar: resumen con la plantilla del final y 🛑 **STOP** hasta recibir `OK fase N, continúa`.
9. No cambies la lógica del agente (enrutado, tools, RAG, memoria, guardias) ni los nombres de sus estados. No mezcles nada del contrato SSE/RFP de la Parte 1 (`rfp_ticket_created`, `Ticket`, `EventBroker` de `services/realtime/`) en el chat.
10. Si algo del código contradice una decisión Dn, para y pregunta: no improvises.

---

## BRIEFING de la Parte 2 — lo esencial (copiado para no depender del fichero)

- **Quién lo pide:** Valentina Cruz, Customer Experience. **Quién lo usa:** los clientes (marcas B2B y destinatarios B2C) que chatean con el agente. Caso típico: el agente responde a «rastreo» cuando querían una devolución y hoy no se le puede redirigir hasta que termina.
- **Agente:** el **First-line CX agent** (tracking, devoluciones, FAQ) = el grafo `trackflow_support_agent` de `services/agent/`. No cambiar su lógica ni sus herramientas.
- **Entidad `ChatSession`:** `session_id`, `agent_id` (`first_line_cx`), `user_id` (el cliente que chatea), `client_id`, `status` (`active`, `interrupted`, `closed`), `created_at`.
- `session_id` va en el handshake del WebSocket (y, si hay checkpoint, como `thread_id`) para rehidratar al reconectar.
- **Auth:** el **mismo JWT** que la API del backoffice (y que el SSE de la Parte 1); preferible `?token=` en la URL y/o primer frame de auth; rechazar antes de cualquier evento de chat si falta o es inválido.
- **Eventos sugeridos** (sobre `{"event": ..., "data": {...}}`):
  ```json
  {"event": "token_chunk", "data": {"session_id": "chat_0219", "token": "Tu", "sequence": 7}}
  {"event": "interrupt_requested", "data": {"session_id": "chat_0219", "new_input": "espera, quiero hacer una devolución, no rastrear el pedido"}}
  {"event": "generation_interrupted", "data": {"session_id": "chat_0219", "message_id": "msg_0449", "status": "interrupted"}}
  {"event": "generation_completed", "data": {"session_id": "chat_0219", "message_id": "msg_0450"}}
  {"event": "session_snapshot", "data": {"session_id": "chat_0219", "messages": []}}
  {"event": "user_message", "data": {"session_id": "chat_0219", "text": "..."}}
  ```
- **Pub/sub:** un canal por sesión, `chat.<session_id>`; productor (el agente generando) desacoplado de los consumidores (las conexiones WS). En memoria es aceptable con un solo proceso; Redis no es obligatorio.
- **Restricciones:** nombres de campos y entidades = los del BRIEFING (sin ids paralelos para la misma sesión); no mezclar los payloads RFP de la Parte 1.

## Rúbrica resumida (lo que se evalúa)

- Tokens en vivo en la UI (efecto de escritura), no la respuesta entera al final.
- WS con el **mismo JWT** (query y/o primer frame); clientes sin auth rechazados.
- WS ligado a una conversación existente por `session_id` (y/o `thread_id`) en la URL.
- Interrupción a mitad: **aborta de forma medible** (cero tokens más), mensaje parcial conservado como `interrupted`, y la siguiente respuesta es un **turno nuevo** que refleja `new_input`. No usar `interrupt()` HITL como sustituto.
- Reconexión con backoff progresivo y el mismo `session_id` → **rehidratación** desde historial/checkpoint antes de aceptar tokens nuevos.
- Productor desacoplado de los consumidores (pub/sub); eventos nombrados y estructurados.
- Nombres = BRIEFING de la Parte 2.
- Tests del contrato (`token_chunk`, `generation_interrupted`, `generation_completed`) + verificación documentada de abort y de reconexión.
- PR con las 3 preguntas de diseño respondidas.

---

## Decisiones ya tomadas (no improvisar)

| # | Decisión | Justificación |
|---|----------|---------------|
| D1 | **Extender el agente existente, no una app paralela.** Subpaquete `services/agent/chat/` cuyo router se incluye dentro del router de `services/agent/router.py` (prefijo resultante `/agent/chat`). `services/api/main.py` no cambia. | El enunciado pide extender la ruta que hoy invoca al agente (`POST /agent/query`, `router.py:78`). |
| D2 | **Modo de streaming de LangGraph: `custom`** (`get_stream_writer()`), combinado con `values` para el estado final: `graph.stream(initial, config, stream_mode=["custom", "values"])`. **No** `messages`. | `generate_answer` llama al SDK de OpenAI en crudo (`harness/generation.py:30`, `chat.completions.create`), no a un chat model de LangChain: `messages` no vería ningún token. `custom` emite exactamente lo que el nodo decide y `values` da el estado final que ya usa el trace. |
| D3 | **Streaming en la llamada al LLM, opt-in.** En `harness/generation.py`: `_complete` acepta `stream=True` y entonces itera `chat.completions.create(..., stream=True)`, llama `writer({"token": delta})` por cada delta no vacío y devuelve el texto completo. Lo activa `generate_answer` solo si `langgraph.config.get_config()["configurable"].get("stream_tokens")` es verdadero (si `get_config()` lanza `RuntimeError` fuera de un grafo → camino actual sin streaming). Después sigue igual: `output_guard.check_rag_answer`, `unsupported_figures`, etc. | El agente no cambia de lógica; los evals y `POST /agent/query` siguen en el camino no streaming. |
| D4 | **Abort genuino, cooperativo y medible.** `config["configurable"]["cancel_event"]` es un `threading.Event`. En el bucle de deltas: si está activo → `stream.close()` (cierra la respuesta HTTP del modelo) y `raise GenerationCancelled` (nueva excepción en `harness/generation.py`). Además `run_agent` comprueba el evento entre chunks de `graph.stream` y sale del bucle (el generador se cierra, no se ejecutan más nodos). Contadores en log: `tokens_sent`, `stream_closed`, `dropped_after_abort`. **No se usa `interrupt()` de LangGraph** (eso es una pausa HITL del grafo; aquí no hay pausa: la generación se descarta y empieza otro turno). | Criterio de aceptación: «abortar genuinamente la generación en curso — no solo ignorar la respuesta». Una llamada al LLM del enrutador ya en vuelo no emite tokens: se corta en el siguiente límite de nodo (se documenta). |
| D5 | **`run_agent(..., on_token=None, cancel_event=None)`** en `services/agent/runner.py`. Con `on_token`: `config["configurable"]` añade `stream_tokens=True` y `cancel_event`; usa `graph.stream` (D2), reenvía cada chunk `custom` a `on_token(token)` y toma el último `values` como `final_state`. Si se cancela: guarda el trace con `status = "interrupted"` y lanza `AgentRunCancelled(run_id)`. Sin `on_token`: exactamente el `graph.invoke` de hoy. `thread_id` del checkpointer sigue siendo el `run_id` de cada turno. | Reutiliza trace, guardias y memoria sin duplicar `run_agent`. |
| D6 | **`thread_id` ≠ `session_id`, a propósito.** La sesión se ata por `session_id` en la URL del WS, se pasa al agente como `conversation_id` (memoria: propuestas pendientes por conversación) y se **rehidrata desde el historial persistido** (`chat_messages`). El checkpointer no se reutiliza entre turnos. | `state.py:38`: el estado del grafo no es historial; reutilizar el `thread_id` arrastraría `rag_answer`, `ticket_result`… al turno siguiente y cambiaría las decisiones de `compose_answer`. El enunciado admite «checkpoint **y/o** historial». Se explica en el PR. |
| D7 | **Persistencia** en PostgreSQL (Supabase) con SQLModel, mismo patrón que RFPs: `services/agent/chat/store.py` con el protocolo `ChatStore`, `InMemoryChatStore` (tests) y `SqlChatStore`; tablas `chat_sessions` (campos del BRIEFING) y `chat_messages` (`message_id`, `session_id`, `role` `user`/`assistant`, `text`, `status` `streaming`/`completed`/`interrupted`/`error`, `run_id`, `created_at`, `updated_at`). DDL idempotente en `services/sql/006_chat_sessions.sql` (checks de `status`, `role`, índice `(session_id, created_at)`, RLS como en 003–005); `SQLModel.metadata.create_all` al arrancar también las crea. Llamadas a la BD desde el WS con `run_in_threadpool`. Sin `engine` → `POST` responde 503 y el WS cierra con 1011. | Rehidratar también tras reiniciar la API, no solo tras un corte de red. |
| D8 | **Ids:** `session_id = "chat_" + uuid4().hex[:12]`, `message_id = "msg_" + uuid4().hex[:12]`, `agent_id = "first_line_cx"`, `user_id` = `id` del usuario del JWT, `client_id` del cuerpo del `POST` (texto `^[A-Za-z0-9_-]{1,40}$`; la UI propone uno real del sistema, que confirmas en la Fase 0). | Formato del BRIEFING (`chat_…`, `msg_…`) sin ids paralelos. |
| D9 | **Rutas.** `POST /agent/chat/sessions` (`{client_id}` → 201 `ChatSession`, `response_model`) y WS `/agent/chat/sessions/{session_id}/ws?token=<JWT>`. Contrato de rutas **52 → 53** (los WS son `APIWebSocketRoute` y no cuentan en `_api_routes`); añade además una aserción de que existe la ruta WS. | Trampa conocida de `tests/test_serialization_contracts.py:109`. |
| D10 | **Auth del WS por `?token=`.** Se valida **antes de cualquier evento**: `get_current_user(token)` (es una función normal, `security.py:45`). Fallo → `accept()` + `close(4401, "unauthorized")` sin enviar nada. Sesión inexistente → `4404`; usuario que no es el dueño ni `admin`/`manager` → `4403`. Se acepta y se cierra (en vez de rechazar el handshake) para que el navegador reciba el código y el cliente **no** reintente. Filtro de logging que redacta `token=…` en los logs de uvicorn (`uvicorn.error` y `uvicorn.access`), porque la línea `"WebSocket /…?token=…" [accepted]` lo imprimiría. | Los navegadores no permiten `Authorization` en el handshake (enunciado). |
| D11 | **Pub/sub en memoria** `services/agent/chat/pubsub.py` (`ChatPubSub`): canal `chat.<session_id>`, una `asyncio.Queue(maxsize=1000)` por suscriptor, `publish()` **thread-safe** con `loop.call_soon_threadsafe` (el agente corre en un hilo). Cola llena → ese suscriptor se cierra con 1013 (el cliente reconecta y rehidrata). Independiente del `EventBroker` SSE de la Parte 1. | Productor/consumidor evaluado; un solo proceso uvicorn. |
| D12 | **Productor único por sesión** `services/agent/chat/turns.py` (`ChatTurnManager`, singleton del proceso): `active[session_id] = Generation(message_id, cancel_event, task, text, sequence)`. Un turno = `asyncio.to_thread(run_agent, text, conversation_id=session_id, user=owner, on_token=…, cancel_event=…)`. **El handler WS nunca llama al agente**: solo reenvía comandos al manager y publica en su socket lo que lee de su cola. Varias conexiones (el cliente y un supervisor) reciben los mismos eventos y el agente se llama **una vez por turno**. Si el dueño se desconecta, el turno sigue y se persiste al terminar. | Pregunta de diseño 2. |
| D13 | **Contrato de eventos** (sobre `{"event", "data"}`; todo `data` lleva `session_id`):<br>**Cliente → servidor:** `user_message` `{session_id, text}` (1–500 caracteres tras `strip`); `interrupt_requested` `{session_id, new_input?}`.<br>**Servidor → cliente:** `session_snapshot` `{session_id, session, messages, active_generation}` (`active_generation` = `{message_id, text, sequence}` o `null`); `user_message` `{session_id, message_id, text, created_at}` (eco a todos los suscriptores); `generation_started` `{session_id, message_id}`; `token_chunk` `{session_id, message_id, token, sequence}` (`sequence` empieza en 1 por mensaje); `generation_interrupted` `{session_id, message_id, status: "interrupted"}`; `generation_completed` `{session_id, message_id, answer, status, sources}` (`answer` = respuesta final ya pasada por la guardia de salida; `status`/`sources` = los de `AgentQueryResponse`); `chat_error` `{session_id, code, detail, message_id?}` con `code` ∈ `invalid_message`, `generation_in_progress`, `nothing_to_interrupt`, `forbidden`, `agent_unavailable`. Esquemas Pydantic en `services/agent/chat/schemas.py`. | Nombres del BRIEFING; los extra (`generation_started`, `chat_error`, `message_id` en `token_chunk`) son necesarios y van documentados. |
| D14 | **Interrupción** (`interrupt_requested` del dueño con turno activo): (1) `cancel_event.set()`; (2) desde ese instante el manager **descarta** cualquier token tardío de ese `message_id` (contador `dropped_after_abort`, que debe quedarse en 0); (3) persiste el mensaje del asistente con el texto ya emitido y `status = "interrupted"`, y la sesión pasa a `interrupted`; (4) publica `generation_interrupted`; (5) espera a que termine el hilo anterior (máx. 5 s, log si no); (6) si llega `new_input`: guarda un `user_message` nuevo, publica su eco, la sesión vuelve a `active` y arranca un **turno nuevo** con otro `message_id`. El mensaje interrumpido **nunca** se borra ni se sobrescribe. Sin turno activo → `chat_error nothing_to_interrupt`. `user_message` con turno activo → `chat_error generation_in_progress` (para redirigir se usa `interrupt_requested`). `closed` queda como valor válido del BRIEFING, sin endpoint en esta entrega. | Criterios de aceptación del ticket. |
| D15 | **Rutas sin LLM** (plantillas de tools, guardrail, `no_context`, memoria): no hay tokens que streamear; antes de `generation_completed` se emite la respuesta final como **un único** `token_chunk`. Con LLM, `generation_completed.answer` es la respuesta compuesta y guardada: la UI deja ese texto como definitivo (casi siempre coincide con lo streameado; difiere si `compose_answer` añade secciones o la guardia de salida bloquea). Se documenta. | Honestidad: no se simulan tokens; la guardia de salida conserva la última palabra. |
| D16 | **Rehidratación.** Al conectar: auth → sesión → suscribirse al canal **primero** → leer historial + `active_generation` del manager → enviar `session_snapshot` **antes que nada** → reenviar la cola. El cliente descarta los `token_chunk` hasta recibir el snapshot y después los que tengan `sequence <= active_generation.sequence`. | «Restaurar contexto, no solo reabrir el socket». Sin huecos ni duplicados en la ventana de reconexión. |
| D17 | **Cliente** `uis/backoffice/src/lib/chat-ws.ts`: `connectChatSocket({ sessionId, onEvent, onStatus })` con `WebSocket` nativo a `${wss|ws}://${location.host}/api/backend/agent/chat/sessions/{id}/ws?token=…` (mismo proxy `/api/backend` de `next.config.ts`; en Codespaces el navegador no llega a `:8000`). **Backoff** 1, 2, 4, 8, 16 s, tope 30 s, jitter ±20 %, reinicio tras un `session_snapshot`; códigos 4401/4403/4404 → no reintenta; `offline` cierra y `online` reconecta ya. Logs `[chat-ws]` de cada intento y retardo (evidencia). Tipos, `createChatSession()` y reductor de eventos en `src/lib/support-chat.ts`. Si el proxy de Next no hiciera el upgrade WS, **para y avisa** (alternativa: puerto 8000 reenviado; se decide entonces). | Mismo enfoque probado en la Parte 1. |
| D18 | **UI** nueva página `uis/backoffice/src/app/support-chat/page.tsx` («Chat de soporte», enlace en `BackofficeNav`). Lista de mensajes; el del asistente crece token a token con cursor; badge ámbar **«Interrumpido»** en los parciales; botón **«Detener»**; el input **sigue activo** mientras responde y enviar durante la respuesta manda `interrupt_requested` con `new_input`; indicador «Conectado» / «Reconectando en N s… (intento k)» / «Rehidratando…» / «Sesión caducada»; botón «Nueva conversación»; `session_id` en `localStorage` (`trackflow.chat_session_id`); `?session=<id>` para unirse a otra sesión: si no eres el dueño, modo **«Observando»** (input desactivado). `/knowledge` (Asistente comercial, RAG del Hito 7) **no se toca**. | No hay ninguna UI que llame hoy a `/agent/query`; la única de pregunta/respuesta es `/knowledge`, que es otro producto (equipo comercial de Miguel Torres). Se explica en el PR. |
| D19 | **Tests deterministas** sin LLM ni BD: el router lee `get_chat_store()` y `get_turn_runner()` (dependencias sobreescribibles); los tests usan `InMemoryChatStore` y un runner falso que emite tokens con pausas y respeta `cancel_event`, y registran cuántas veces se llamó. La prueba del abort real del stream usa un cliente OpenAI falso con `stream=True` (objeto iterable con `close()`). | Repetibles en CI. |
| D20 | **Script de sondeo** `scripts/agent_chat_ws_probe.py` (usa `websockets`, ya instalado): `--no-token` (muestra el cierre 4401), `--session`, `--question`, `--interrupt-after N --new-input "…"`; imprime cada evento con su hora y al final `tokens_after_interrupt_for_old_message = 0` y el `message_id` del turno nuevo. Token por la variable `TRACKFLOW_TOKEN`. | Evidencia medible del abort, además de DevTools. |

## Hallazgos del código (confírmalos en la Fase 0 con fichero:línea)

- `services/agent/router.py:78-85`: `POST /agent/query` → `runner.run_agent(body.question, conversation_id=…, user=user)`; petición/respuesta única. Prefijo `/agent`.
- `services/agent/runner.py:66` `run_config` → `thread_id = run_id`; `:138` `run_agent`; `:173` `graph.invoke(initial, config)`; trace con `build_trace`/`save_trace`; `AgentRunError`.
- `services/agent/harness/generation.py:23-30`: `_complete` → `get_generation_client().chat.completions.create(**kwargs)` sin streaming; `:34` `generate_answer`.
- `services/agent/nodes.py:274`: `generate_answer` → `output_guard.check_rag_answer(...)`; `compose_answer` une secciones y pasa la guardia de salida.
- `services/agent/graph.py`: `AGENT_GRAPH = compile_graph()` con `InMemorySaver`; nodo `generate_answer` envuelto en `traced()`.
- `services/agent/state.py:38`: el estado no incluye historial a propósito.
- `services/api/security.py:45`: `get_current_user(token)`; `services/api/main.py:156`: `include_router(agent_router)`.
- `tests/test_serialization_contracts.py:109`: `assert len(routes) == 52`.
- `uis/backoffice/next.config.ts:7`: rewrite `/api/backend/:path*` → API; `src/lib/api.ts`: `getAuthToken()`, `fetchWithAuth`.
- `uis/backoffice/src/components/BackofficeNav.tsx:14-15`: enlaces «Asistente comercial» y «RFPs». Ningún fichero de `uis/` llama a `/agent/query`.
- Versiones: `langgraph` 1.2.24, `uvicorn` 0.52.4, `websockets` 16.1.1 (transitiva), Next 16.

## Ficheros autorizados

- **Nuevos:** `services/agent/chat/__init__.py`, `schemas.py`, `store.py`, `pubsub.py`, `turns.py`, `router.py`, `logging_filters.py`; `services/sql/006_chat_sessions.sql`; `uis/backoffice/src/lib/chat-ws.ts`, `uis/backoffice/src/lib/support-chat.ts`, `uis/backoffice/src/app/support-chat/page.tsx`; `scripts/agent_chat_ws_probe.py`; `tests/pipelines/test_agent_streaming.py`, `tests/test_agent_chat_pubsub.py`, `tests/test_agent_chat_ws.py`; `docs/agent-chat-ws/chat-ws-design.md`, `docs/agent-chat-ws/manual-verification.md`, `docs/agent-chat-ws/evidence/` (capturas); `memory-bank/history/2026-11-26_websocket-chat.md`, `prompts/websocket-chat/prompt.md`.
- **Modificados:** `services/agent/harness/generation.py`, `services/agent/runner.py`, `services/agent/router.py` (solo `include_router` del chat), `tests/test_serialization_contracts.py`, `uis/backoffice/src/components/BackofficeNav.tsx`, `memory-bank/progress.md`, `prompts/README.md` (fila nueva y la de `sse-notifications` a «PR abierto · #37»).
- Cualquier otro fichero: pregunta antes.

---

## Fase 0 — Reconocimiento y línea base

| # | Acción | Commit |
|---|--------|--------|
| 0.1 | `git branch --show-current` = `feature/websocket-chat`; `git log -1 --oneline` = `9f2b6b4 docs: actualiza el progreso con la verificación de las notificaciones SSE`. Si no, STOP. | — |
| 0.2 | Leer `AGENTS.md`, `uis/backoffice/AGENTS.md`, la primera entrada de `memory-bank/progress.md` y confirmar los hallazgos (fichero:línea). | — |
| 0.3 | Comprobar sin instalar nada: `python -c "import websockets; print(websockets.__version__)"` y `python -c "from langgraph.config import get_config, get_stream_writer; print('ok')"`. Si alguno falla, STOP (Marisin decidirá un `uv add`). | — |
| 0.4 | `pytest -q tests/test_agent_routes.py tests/pipelines/test_agent_graph.py tests/test_serialization_contracts.py tests/test_realtime_sse.py` → línea base en verde (indica el total). | — |
| 0.5 | Localizar 2–3 `client_id` reales del sistema (datos de reporting o `CONTEXT.md`) para el valor por defecto de la UI (D8). Solo informar. | — |
| 0.6 | Leer `trackflow-BRIEFING.es.md` (raíz) y comprobar que es el de la **Parte 2** y coincide con «lo esencial». No moverlo ni commitearlo. Si aparece en `git status`, para y avisa (falta en `.git/info/exclude`). | — |
| 0.7 | Comprobar que el plan y el prompt están en `memory-bank/history/2026-11-26_websocket-chat.md` y `prompts/websocket-chat/prompt.md`; añadir la fila `websocket-chat` a `prompts/README.md` y poner la de `sse-notifications` como «PR abierto» · `#37`. | `docs: añade el plan y el prompt del chat por WebSocket` |

✅ Aceptación: rama correcta, hallazgos confirmados, imports OK, línea base verde, BRIEFING leído y fuera de git. 🛑 STOP.

## Fase 1 — Streaming y abort del agente (`services/agent/`)

| # | Acción | Commit |
|---|--------|--------|
| 1.1 | `harness/generation.py` (D3, D4): `GenerationCancelled`, `_complete(..., stream=False)` con el bucle de deltas, `writer`, `cancel_event` y `stream.close()`; `generate_answer` decide con `get_config()`. El camino sin streaming queda byte a byte igual. | `feat: añade la generación en streaming cancelable del agente de CX` |
| 1.2 | `runner.py` (D5): `run_agent(..., on_token=None, cancel_event=None)`, `graph.stream(stream_mode=["custom", "values"])`, corte entre chunks, `AgentRunCancelled`, trace `status = "interrupted"`, log `agent run_id=… cancelled tokens_sent=… stream_closed=…`. | `feat: permite ejecutar el agente con tokens en vivo y cancelación` |
| 1.3 | `tests/pipelines/test_agent_streaming.py` (D19), con el grafo real y los dobles de los tests existentes del agente: (a) `on_token` recibe los deltas en orden y su concatenación = `rag_answer`; (b) sin `on_token` el resultado es idéntico al de hoy y el cliente falso se llama con `stream` ausente/falso; (c) cancelar tras el 3.er delta → `close()` llamado, deltas consumidos < disponibles, `AgentRunCancelled`, trace `interrupted`, ningún `on_token` más; (d) cancelar antes de `generate_answer` → no se llama al LLM de generación; (e) `generate_answer` fuera de un grafo no falla (sin streaming). | `test: prueba el streaming y la cancelación del agente` |

✅ Aceptación: `pytest -q tests/pipelines/test_agent_streaming.py tests/pipelines/test_agent_graph.py tests/test_agent_routes.py tests/pipelines/test_agent_evals.py` verde (los evals grabados intactos). 🛑 STOP.

## Fase 2 — Backend del chat (`services/agent/chat/`)

| # | Acción | Commit |
|---|--------|--------|
| 2.1 | `schemas.py` (D8, D13): `ChatSession`, `ChatMessage`, `ChatSessionCreate`, `ChatSnapshot` y un modelo por evento (cliente y servidor) + `dump_event(name, data)`. | `feat: añade los contratos de la sesión y los eventos del chat` |
| 2.2 | `store.py` + `services/sql/006_chat_sessions.sql` (D7). | `feat: persiste las sesiones y los mensajes del chat en PostgreSQL` |
| 2.3 | `pubsub.py` (D11). | `feat: añade el pub/sub en memoria por sesión de chat` |
| 2.4 | `turns.py` (D12, D14, D15): `ChatTurnManager` (`start_turn`, `interrupt`, `active_generation`, contadores) y `get_turn_runner()` que envuelve `runner.run_agent`. | `feat: añade el gestor de turnos con abort de la generación` |
| 2.5 | `router.py` + `logging_filters.py` (D9, D10, D16): `POST /agent/chat/sessions` y el WS; incluirlo en `services/agent/router.py`; registrar el filtro de logs al importar. | `feat: añade el WebSocket del chat protegido con JWT` |
| 2.6 | Contrato de rutas 52 → 53 + aserción de la ruta WS (D9). | `test: actualiza el contrato de rutas con el chat por WebSocket` |

✅ Aceptación: `pytest -q tests/test_serialization_contracts.py tests/test_agent_routes.py` verde. Comandos para Marisin: ejecutar `services/sql/006_chat_sessions.sql` en Supabase (o confiar en `create_all`), arrancar la API (`--timeout-graceful-shutdown 3`) y el probe sin token. 🛑 STOP.

## Fase 3 — Tests del contrato WebSocket (`tests/`)

| # | Acción | Commit |
|---|--------|--------|
| 3.1 | `tests/test_agent_chat_pubsub.py`: dos suscriptores del mismo canal reciben lo mismo y en orden; canales aislados; `publish` desde otro hilo; cola llena → cierre de ese suscriptor; `unsubscribe` limpia. | `test: prueba el pub/sub del chat` |
| 3.2 | `tests/test_agent_chat_ws.py` (D19): (a) sin token / token inválido → cierre 4401 sin ningún frame; (b) sesión inexistente → 4404; otro usuario `user` → 4403; un `manager` sí entra; (c) el primer frame es `session_snapshot`; (d) `user_message` → eco `user_message` con `message_id`, `generation_started`, `token_chunk` con `sequence` 1..n consecutivos y `generation_completed` con `answer`; mensajes persistidos `completed`; (e) **interrupción:** tras 2 tokens, `interrupt_requested` con `new_input` → `generation_interrupted` (`status = "interrupted"`), **ningún** `token_chunk` del `message_id` viejo después, mensaje parcial guardado `interrupted` con exactamente los tokens emitidos, nuevo `user_message` = `new_input`, turno nuevo con otro `message_id` cuya pregunta es `new_input`, `dropped_after_abort == 0` y el runner falso vio `cancel_event` activo; (f) `user_message` con turno activo → `chat_error generation_in_progress`; `interrupt_requested` sin turno → `nothing_to_interrupt`; texto vacío o > 500 → `invalid_message`; (g) **reconexión:** cerrar y volver a conectar con el mismo `session_id` → `session_snapshot` con el historial (incluido el `interrupted`); reconectar a mitad de turno → `active_generation` con el texto parcial y los tokens siguientes con `sequence` mayor; (h) **supervisor:** dueño + `manager` conectados → ambos reciben la misma secuencia y el runner se llama **una** vez; el observador que envía `user_message` recibe `chat_error forbidden`; (i) `POST /agent/chat/sessions` → 201 con los campos del BRIEFING, `agent_id = first_line_cx`, `status = active`; sin token → 401. | `test: prueba el contrato de eventos del WebSocket del chat` |

✅ Aceptación: suite completa `pytest -q` verde (indica el total). 🛑 STOP.

## Fase 4 — Frontend (`uis/backoffice`)

| # | Acción | Commit |
|---|--------|--------|
| 4.1 | `src/lib/support-chat.ts`: tipos del contrato (D13), `createChatSession(clientId)`, reductor puro `applyChatEvent(state, event)` (snapshot, dedupe por `sequence`, interrumpido, completado con `answer` definitivo). | `feat: añade el modelo del chat de soporte en el backoffice` |
| 4.2 | `src/lib/chat-ws.ts` (D17). | `feat: añade el cliente WebSocket con backoff y rehidratación` |
| 4.3 | `src/app/support-chat/page.tsx` + enlace «Chat de soporte» en `BackofficeNav.tsx` (D18). | `feat: muestra la respuesta del agente en vivo y permite interrumpirla` |
| 4.4 | `npm run typecheck` (y `git restore uis/backoffice/tsconfig.tsbuildinfo`). | — |

✅ Aceptación: typecheck limpio. Comandos para Marisin: `npm run build` + `npm run start` (en `dev` el HMR recarga la página al volver la red y estropea la prueba de reconexión) y prueba en el navegador. Si el upgrade WS por `/api/backend` falla, STOP y avisa. 🛑 STOP.

## Fase 5 — Sondeo, documentación y verificación manual

| # | Acción | Commit |
|---|--------|--------|
| 5.1 | `scripts/agent_chat_ws_probe.py` (D20). | `feat: añade el script de sondeo del WebSocket del chat` |
| 5.2 | `docs/agent-chat-ws/chat-ws-design.md`: por qué WS y no SSE, arquitectura en texto (UI → proxy Next → WS → `ChatTurnManager` → `run_agent` en hilo → `chat.<session_id>` → N sockets), contrato con ejemplos reales, D2 (por qué `custom`), D4/D14 (abort frente a `interrupt()` HITL), D6 (por qué el `thread_id` no es el `session_id`), D15, D16, auth y redacción del token, límites (un proceso; escalar con Redis pub/sub, que ya hay por Celery, y afinidad de sesión) y **las 3 preguntas de diseño respondidas**. | `docs: documenta el diseño del chat por WebSocket` |
| 5.3 | `docs/agent-chat-ws/manual-verification.md`: el guion de abajo con huecos para resultados y capturas. | `docs: añade el guion de verificación manual del chat` |
| 5.4 | Entrada nueva **arriba** de `memory-bank/progress.md`. | `docs: registra el chat por WebSocket en el progreso` |

**Guion de verificación manual (lo ejecuta Marisin; capturas `chatws-*.png` en `docs/agent-chat-ws/evidence/`):**
1. Probe `--no-token` → cierre 4401 sin eventos.
2. Backoffice → «Chat de soporte» → «Nueva conversación» → «Conectado»; pregunta de política (p. ej. devoluciones en España) → la respuesta se escribe token a token; DevTools → Network → WS → Messages con `token_chunk` y `sequence` creciente.
3. Durante la respuesta, enviar «espera, quiero hacer una devolución, no rastrear el pedido» → `generation_interrupted`, parcial con «Interrumpido», mensaje nuevo del usuario y respuesta nueva; en Messages, ningún `token_chunk` del `message_id` viejo tras el `generation_interrupted`; log de la API con `stream_closed=True` y `dropped_after_abort=0`.
4. Probe `--interrupt-after 5` → `tokens_after_interrupt_for_old_message = 0`.
5. DevTools → **Offline** → `[chat-ws]` con retardos crecientes; **Online** → reconecta, `session_snapshot`, historial intacto (incluido el interrumpido).
6. Reiniciar la API → reconexión con backoff y snapshot desde PostgreSQL. F5 → misma sesión desde `localStorage`.
7. Supervisor: otra ventana (incógnito) con un usuario `admin`/`manager` y `?session=<id>` → «Observando», ve los mismos tokens; el log muestra una sola corrida del agente por turno.

✅ Aceptación: docs completos. 🛑 STOP final.

---

## Plantilla de resumen por fase

```
Fase N — hecha
Commits: <hash> <mensaje> (uno por línea)
Ficheros tocados: …
Validaciones: <comando> → <resultado>
Dudas / desviaciones del plan: …
Comandos para Marisin: …
```

## Checklist final de la rúbrica

- [ ] Tokens en vivo en «Chat de soporte» (`token_chunk` con `sequence`), modo `custom` de LangGraph justificado
- [ ] WS `/agent/chat/sessions/{session_id}/ws?token=` con el mismo JWT; 4401 antes de cualquier evento; 4404/4403
- [ ] Sesión existente (`POST /agent/chat/sessions`) con los campos del BRIEFING; contrato 53 rutas
- [ ] Abort real: `stream.close()` + `cancel_event`, cero tokens del mensaje viejo, `dropped_after_abort = 0`; sin `interrupt()` HITL
- [ ] Parcial conservado `interrupted`; turno nuevo con otro `message_id` que refleja `new_input`
- [ ] Reconexión con backoff (1→30 s, jitter) y `session_snapshot` desde PostgreSQL antes de aceptar tokens
- [ ] Pub/sub `chat.<session_id>`: productor único por sesión, N consumidores, agente llamado una vez por turno
- [ ] Eventos nombrados y estructurados (D13); nada del contrato RFP/SSE de la Parte 1
- [ ] Tests: streaming/abort del agente, pub/sub, contrato WS; suite completa verde
- [ ] Verificación manual documentada con capturas (abort y reconexión)
- [ ] PR con las 3 preguntas de diseño respondidas
- [ ] `git log --all -- trackflow-BRIEFING.es.md` vacío
