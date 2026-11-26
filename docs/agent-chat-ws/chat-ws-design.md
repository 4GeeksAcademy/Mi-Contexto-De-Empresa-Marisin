# Diseño — Chat del First-line CX agent por WebSocket (Sistemas en tiempo real · Parte 2)

**Quién lo pide:** Valentina Cruz (Customer Experience). **Quién lo usa:** los clientes
(marcas B2B y destinatarios B2C) que chatean con el agente de tracking, devoluciones y
preguntas frecuentes. **Problema:** hoy la respuesta llega entera al final y, si el agente
va por el intent equivocado («rastreo» cuando querían una devolución), no se le puede
redirigir hasta que termina.

**Qué cambia:** solo el canal. El agente es el mismo grafo `trackflow_support_agent` de
`services/agent/` (mismos nodos, tools, RAG, memoria y guardias). Sin `on_token`,
`run_agent` y `POST /agent/query` se comportan exactamente como antes (los evals grabados
no cambian).

Código: `services/agent/chat/` (backend), `services/agent/harness/generation.py` y
`services/agent/runner.py` (streaming y abort), `uis/backoffice/src/lib/{support-chat,chat-ws}.ts`
y `uis/backoffice/src/app/support-chat/page.tsx` (UI), `scripts/agent_chat_ws_probe.py`
(sonda), `services/sql/006_chat_sessions.sql` (DDL). Verificación: [`manual-verification.md`](manual-verification.md).

---

## 1. Por qué WebSocket y no el SSE de la Parte 1

El SSE de la Parte 1 (`GET /realtime/events`) es un canal **solo servidor → cliente**: sirve
para avisar de una RFP nueva. Aquí el cliente tiene que **hablar mientras el servidor
sigue hablando**: enviar `interrupt_requested` (con el nuevo texto) en mitad de una ráfaga
de `token_chunk`, y que el servidor lo procese sin esperar a que termine la respuesta. Con
SSE habría que abrir un segundo canal (un `POST` aparte) y correlacionarlo con el stream; el
WebSocket da los dos sentidos en una sola conexión autenticada y ordenada. Se detalla en la
[pregunta 1](#pregunta-1).

## 2. Arquitectura

```
Navegador (Chat de soporte)
  │  WebSocket ws(s)://<host>/api/backend/agent/chat/sessions/{session_id}/ws?token=<JWT>
  ▼
Proxy de Next (/api/backend → :8000, hace el upgrade: 101 Switching Protocols)
  ▼
FastAPI  WS /agent/chat/sessions/{session_id}/ws          (services/agent/chat/router.py)
  │  auth (JWT) → sesión → subscribe(chat.<session_id>) → session_snapshot → reenviar cola
  │  los comandos del cliente van al gestor; el handler NUNCA llama al agente
  ▼
ChatTurnManager (productor único por sesión)               (services/agent/chat/turns.py)
  │  asyncio.to_thread(run_agent, text, conversation_id=session_id, user=dueño,
  │                    on_token=…, cancel_event=threading.Event())
  ▼
run_agent → graph.stream(stream_mode=["custom", "values"])  (hilo del agente)
  │  generate_answer → chat.completions.create(stream=True) → writer({"token": delta})
  │  cada token vuelve al event loop con loop.call_soon_threadsafe
  ▼
ChatPubSub  canal chat.<session_id>                        (services/agent/chat/pubsub.py)
  │  una asyncio.Queue(maxsize=1000) por conexión; publish() thread-safe
  ├──► WS del cliente (dueño)
  └──► WS del supervisor (admin/manager, «Observando»)
                │
PostgreSQL (Supabase): chat_sessions, chat_messages        (services/agent/chat/store.py)
```

- **Rutas:** `POST /agent/chat/sessions` `{client_id}` → 201 `ChatSession`, y el WebSocket. El
  subrouter se incluye en `services/agent/router.py` (prefijo `/agent/chat`); `services/api/main.py`
  no cambia. El contrato de rutas pasa de 52 a 53 (el WebSocket es un `APIWebSocketRoute` y no
  cuenta como `APIRoute`; un test comprueba que existe).
- **Entidad `ChatSession`** (BRIEFING): `session_id` (`chat_` + 12 hex), `agent_id = first_line_cx`,
  `user_id` (usuario del JWT, el dueño), `client_id` (`^[A-Za-z0-9_-]{1,40}$`; la UI ofrece los reales
  `ecowear_usa`, `nova_beauty`, `hydrolife`), `status` (`active`, `interrupted`, `closed`) y `created_at`.
  `closed` es un valor válido del BRIEFING sin endpoint en esta entrega.
- **Mensajes** (`chat_messages`): `message_id` (`msg_` + 12 hex), `session_id`, `role` (`user`/`assistant`),
  `text`, `status` (`streaming` → `completed` / `interrupted` / `error`), `run_id` (trace del agente),
  `created_at`, `updated_at`. Las llamadas a la BD desde el WebSocket van con `run_in_threadpool`.
- El handler de cada conexión corre dos tareas en un **task group de anyio**: el emisor (único
  escritor del socket, lee la cola) y el receptor (comandos). Cuando una termina se cancela la otra.
  Con `asyncio.wait` + `gather` la cancelación del servidor a mitad de la limpieza dejaba el task
  con dos cancelaciones y anyio no la absorbía (se vio en los tests; `fix` aparte).

## 3. Contrato de eventos

Sobre `{"event": …, "data": {…}}`; todo `data` lleva `session_id`. Nombres del BRIEFING; los
añadidos (`generation_started`, `chat_error` y `message_id` en `token_chunk`) son necesarios
para numerar y correlacionar. Esquemas Pydantic en `services/agent/chat/schemas.py`; tipos
TypeScript en `uis/backoffice/src/lib/support-chat.ts`.

**Cliente → servidor**

| Evento | `data` | Notas |
|---|---|---|
| `user_message` | `{session_id, text}` | 1–500 caracteres tras `strip`. Con un turno activo → `chat_error generation_in_progress` (para redirigir se usa `interrupt_requested`). |
| `interrupt_requested` | `{session_id, new_input?}` | Sin turno activo → `chat_error nothing_to_interrupt`. Con `new_input`, abre un turno nuevo. |

**Servidor → cliente**

| Evento | `data` |
|---|---|
| `session_snapshot` | `{session_id, session, messages, active_generation}`; `active_generation` = `{message_id, text, sequence}` o `null`. **Siempre el primer frame.** |
| `user_message` | `{session_id, message_id, text, created_at}` (eco a todas las conexiones) |
| `generation_started` | `{session_id, message_id}` |
| `token_chunk` | `{session_id, message_id, token, sequence}`; `sequence` empieza en 1 por mensaje |
| `generation_interrupted` | `{session_id, message_id, status: "interrupted"}` |
| `generation_completed` | `{session_id, message_id, answer, status, sources}` (`status`/`sources` = los de `AgentQueryResponse`) |
| `chat_error` | `{session_id, code, detail, message_id?}`; `code` ∈ `invalid_message`, `generation_in_progress`, `nothing_to_interrupt`, `forbidden`, `agent_unavailable` |

Un turno con interrupción, tal como lo emite el servidor (ids de ejemplo):

```json
{"event": "user_message", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_a1b2c3d4e5f6", "text": "¿Dónde está mi pedido?", "created_at": "2026-11-26T19:53:25.357672Z"}}
{"event": "generation_started", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_0449aa11bb22"}}
{"event": "token_chunk", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_0449aa11bb22", "token": "Tu", "sequence": 1}}
{"event": "token_chunk", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_0449aa11bb22", "token": " pedido", "sequence": 2}}
{"event": "generation_interrupted", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_0449aa11bb22", "status": "interrupted"}}
{"event": "user_message", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_c7d8e9f0a1b2", "text": "espera, quiero hacer una devolución, no rastrear el pedido", "created_at": "2026-11-26T19:53:26.012004Z"}}
{"event": "generation_started", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_0450cc33dd44"}}
{"event": "token_chunk", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_0450cc33dd44", "token": "Para", "sequence": 1}}
{"event": "generation_completed", "data": {"session_id": "chat_3f9c0a1b2c4d", "message_id": "msg_0450cc33dd44", "answer": "Para iniciar una devolución…\nFuente: Política de Devoluciones", "status": "answered", "sources": ["rag"]}}
```

## 4. Streaming de tokens: modo `custom` de LangGraph (D2, D3)

`generate_answer` llama al SDK de OpenAI en crudo (`chat.completions.create`), no a un chat
model de LangChain, así que `stream_mode="messages"` no vería ningún token. Se usa
`graph.stream(initial, config, stream_mode=["custom", "values"])`:

- `custom`: el nodo decide qué emite. Si la corrida lo pide (`config["configurable"]["stream_tokens"]`,
  que pone `run_agent(on_token=…)`), `_complete` itera `create(..., stream=True)` y llama
  `get_stream_writer()({"token": delta})` por cada delta no vacío. Después sigue igual:
  `output_guard.check_rag_answer`, `unsupported_figures`, `compose_answer`.
- `values`: el último estado es el `final_state` que ya usaban el trace y la respuesta.
- Fuera de un grafo (`get_config()` lanza `RuntimeError`) o sin `stream_tokens` → camino de
  siempre, sin streaming (lo comprueba `tests/pipelines/test_agent_streaming.py`).

El nodo corre en un hilo del pool de LangGraph y cada chunk `custom` llega a `run_agent` en cuanto
se escribe (comprobado antes de implementar). `run_agent` lo reenvía a `on_token`, que lo pasa al
event loop; allí el gestor lo numera (`sequence`) y lo publica.

**Tiempos medidos en el navegador (Marisin, 2026-11-26):** ~3,2 s desde el mensaje hasta el
primer token (enrutado + recuperación RAG, sin tokens), y después **56 tokens en ~250 ms**
(~200 tokens/s, el stream real del modelo). Con esa velocidad, una persona no puede
interrumpir a mitad de los tokens desde la UI: la evidencia principal del abort a mitad de la
respuesta es la sonda (`--interrupt-after N`, §5). Lo que una persona sí hace en la práctica
es interrumpir durante esos ~3,2 s previos: el corte llega en el siguiente límite de nodo y
`generate_answer` ni siquiera llama al modelo (test (d) de `test_agent_streaming.py`).

## 5. Abort real frente a `interrupt()` de LangGraph (D4, D14)

**No se usa `interrupt()`** (HITL): eso pausa el grafo para reanudarlo después con un
`Command`; aquí no hay pausa ni reanudación, la generación **se descarta** y empieza otro
turno. El abort es cooperativo y medible:

1. `interrupt_requested` del dueño → el gestor marca la generación como cancelada
   (desde ese instante descarta cualquier token tardío de ese `message_id`) y activa su
   `cancel_event` (`threading.Event`, que viaja en `config["configurable"]`).
2. En el bucle de deltas de `_complete`: con el evento activo → `stream.close()` (cierra la
   respuesta HTTP del modelo, que deja de enviar tokens) y `raise GenerationCancelled`.
3. `run_agent` también comprueba el evento **antes de cada chunk** de `graph.stream`: ningún token
   que llegue después se reenvía, sale del bucle y cierra el generador (no se ejecutan más nodos).
   El trace se guarda con `status = "interrupted"` y `cancelled: {tokens_sent, stream_closed}`, y
   se lanza `AgentRunCancelled(run_id)`. Log: `agent run_id=… cancelled tokens_sent=… stream_closed=True`.
4. El gestor persiste el parcial (exactamente el texto ya emitido) como `interrupted`, la sesión
   pasa a `interrupted`, publica `generation_interrupted`, espera al hilo (máx. 5 s) y, con
   `new_input`, abre un turno nuevo (la sesión vuelve a `active`).

**Cuándo se detecta.** El abort se detecta **en el siguiente delta del modelo** (el bucle
comprueba el evento en cada chunk que entrega el stream). Si en ese momento hay en vuelo una
llamada del **enrutador** (LLM sin streaming), esa llamada termina antes de cortar: el corte
llega en el siguiente límite de nodo. **Mientras tanto no se reenvía ningún token**: `run_agent`
deja de reenviar en cuanto el evento está activo y el gestor descarta lo que ya estuviera en el
event loop.

**La métrica del abort** es: **cero `token_chunk` del `message_id` viejo después de
`generation_interrupted`**. Es lo que comprueban siempre los tests y la sonda
(`tokens_after_interrupt_for_old_message = 0`). Los contadores de apoyo:

| Contador | Dónde | Qué mide |
|---|---|---|
| `tokens_sent` | log de `run_agent` | tokens reenviados antes del corte |
| `stream_closed` | log de `run_agent` y trace | `True` si `generate_answer` cerró la respuesta del modelo (`False` si el corte llegó antes de llamar al modelo) |
| `dropped_after_abort` | log del gestor (`chat session=… cancelled … dropped_after_abort=…`) | tokens tardíos que el gestor **descartó** porque ya estaban en camino hacia el event loop cuando se marcó la cancelación |

`dropped_after_abort` **no es la métrica**: con el LLM real a ~200 tokens/s puede ser > 0 sin
que sea un fallo (son justo los tokens que el gestor impide publicar). Solo es 0 de forma
determinista con el runner falso de los tests. En la sonda, los `tokens_in_flight` (entre el
envío de `interrupt_requested` y la llegada de `generation_interrupted`) son la misma ventana
vista desde el cliente: ya estaban en la red o en la cola del socket.

## 6. Por qué el `thread_id` del checkpointer no es el `session_id` (D6)

El BRIEFING propone el `session_id` como `thread_id` *si se hace checkpoint*. Aquí no se
reutiliza el checkpoint entre turnos, a propósito: el estado del grafo no es historial
(`state.py`: «no incluye el historial de la conversación»). Reutilizar el `thread_id`
arrastraría `rag_answer`, `ticket_result`, `guardrail`… al turno siguiente y cambiaría las
decisiones de `compose_answer`, es decir, cambiaría la lógica del agente. Por eso:

- cada turno tiene su `run_id`, que sigue siendo el `thread_id` del checkpointer (y el id del trace,
  guardado en `chat_messages.run_id`);
- la sesión se ata por el `session_id` de la URL del WebSocket y se pasa al agente como
  `conversation_id` (la memoria guarda la propuesta pendiente por conversación);
- la conversación se **rehidrata desde el historial persistido** (`chat_messages` en PostgreSQL),
  que sobrevive a cortes de red **y** a reinicios de la API. El enunciado admite «checkpoint y/o historial».

## 7. Rutas sin LLM (D15)

Las plantillas de tools, las guardias, `no_context` y la memoria no generan tokens. No se
simulan: antes de `generation_completed` se emite la respuesta final como **un único**
`token_chunk`. Con LLM, `generation_completed.answer` es la respuesta compuesta y guardada, y la
UI la deja como texto definitivo: casi siempre coincide con lo streameado y difiere si
`compose_answer` añade secciones (ticket + política, notas de memoria) o la guardia de salida
corrige o bloquea. La guardia de salida conserva la última palabra.

## 8. Rehidratación al conectar (D16)

Orden en el servidor: auth → sesión → **suscribirse al canal primero** → leer historial +
`active_generation` del gestor → enviar `session_snapshot` **antes que nada** → reenviar la cola.
Al suscribirse antes de leer no hay hueco; para que tampoco haya duplicados:

- el servidor no reenvía de la cola lo que el snapshot ya contiene: los `token_chunk` del mensaje en
  curso con `sequence <= active_generation.sequence` y los `user_message`/`generation_started` cuyo
  `message_id` ya está en el historial;
- el cliente (`applyChatEvent`) descarta todo hasta el `session_snapshot` de cada conexión, y después
  los `token_chunk` con `sequence` ya aplicada y cualquier token de un mensaje ya `interrupted` o `completed`.

Un mensaje `streaming` sin generación viva (p. ej. la API se reinició a mitad) se muestra en el
snapshot como `error` sin reescribir la BD (así no pisa una respuesta que esté terminando a la vez).

Varias conexiones a la misma sesión reciben los mismos eventos. Si el dueño se desconecta, el
turno sigue y se persiste al terminar; al volver, el snapshot trae el texto ya generado y los
tokens siguientes continúan la numeración.

## 9. Autenticación, permisos y redacción del token (D10)

- El **mismo JWT** que la API del backoffice (y el SSE de la Parte 1), en `?token=`: los navegadores
  no permiten `Authorization` en el handshake. Se valida con `get_current_user(token)` **antes de
  cualquier evento**.
- Cierres propios, **sin enviar ningún frame**: `4401` (falta el token o no es válido), `4404`
  (sesión inexistente), `4403` (ni dueño ni `admin`/`manager`). Se acepta y se cierra en vez de
  rechazar el handshake, para que el navegador reciba el código y el cliente **no** reintente.
  Sin PostgreSQL: `POST` → 503 y el WS cierra con `1011`. Cola llena → `1013` (el cliente
  reconecta y rehidrata).
- Solo el dueño escribe; `admin`/`manager` pueden observar (`?session=<id>` en la UI, modo
  «Observando») y reciben `chat_error forbidden` si envían algo.
- uvicorn registra cada handshake con la ruta y su query (`"WebSocket /…/ws?token=…" [accepted]`).
  `services/agent/chat/logging_filters.py` añade un filtro a `uvicorn.error` y `uvicorn.access` que
  la deja en `token=[redacted]`. La sonda tampoco imprime el token.

## 10. Reconexión en el cliente (D17)

`connectChatSocket()` (`uis/backoffice/src/lib/chat-ws.ts`) usa el `WebSocket` nativo a
`${ws|wss}://${location.host}/api/backend/agent/chat/sessions/{id}/ws?token=…` (mismo proxy que
`api.ts`; en Codespaces el navegador no llega a `:8000`; verificado que el proxy hace el upgrade, 101).

- Backoff 1, 2, 4, 8, 16 s, tope 30 s, jitter ±20 % (el mismo `backoffDelay` del SSE); vuelve a 1 s
  tras un `session_snapshot`. 4401/4403/4404 no se reintentan.
- `offline` cierra el socket; `online` reconecta sin esperar al temporizador.
- Estados en la UI: «Conectando…», «Rehidratando…» (abierto, esperando el snapshot), «Conectado»,
  «Reconectando en N s… (intento k)», «Sesión caducada», «Sin acceso», «La conversación no existe».
- Logs `[chat-ws]` de cada intento, retardo, cierre y snapshot (evidencia en la consola).
- El `session_id` propio se guarda en `localStorage` (`trackflow.chat_session_id`): F5 vuelve a la
  misma conversación.

## 11. Límites y cómo escalaría

- **Un solo proceso uvicorn.** El pub/sub (`ChatPubSub`) y el gestor de turnos (`active`) viven en
  memoria. Con varias instancias: el pub/sub pasa a **Redis pub/sub** (ya lo tenemos por Celery), con
  el mismo canal `chat.<session_id>`, y el productor único por sesión se mantiene con **afinidad de
  sesión** (el balanceador enruta por `session_id`) o con un lock en Redis por sesión. La
  interrupción viajaría como mensaje de control al proceso dueño del turno.
- Un reinicio de la API pierde el turno en curso (su fila queda `streaming` y se muestra como
  `error`). El historial ya persistido no se pierde.
- No hay keep-alive de aplicación: se apoya en los pings de protocolo de uvicorn/websockets y en
  `offline`/`online` del navegador.
- `closed` existe en el modelo, pero no hay endpoint para cerrar una sesión.

## 12. Tests y evidencia

- `tests/pipelines/test_agent_streaming.py` (5): deltas en orden y su concatenación = `rag_answer`;
  sin `on_token` nada cambia; cancelar tras el 3.er delta → `close()` llamado, deltas consumidos <
  disponibles, `AgentRunCancelled`, trace `interrupted`, ningún `on_token` más; cancelar antes de
  `generate_answer` → no se llama al modelo; fuera de un grafo, sin streaming.
- `tests/test_agent_chat_pubsub.py` (6): mismos eventos y orden para dos suscriptores, canales
  aislados, `publish` desde otro hilo, cola llena, `unsubscribe`.
- `tests/test_agent_chat_ws.py` (23): 4401 sin frames, 4404, 4403/manager, snapshot primero, turno
  completo con `sequence` 1..n, ruta sin LLM, **interrupción** (cero `token_chunk` del viejo tras
  `generation_interrupted`, parcial `interrupted` exacto, turno nuevo con `new_input`), errores del
  contrato, **reconexión** (historial con el interrumpido; a mitad de turno sin huecos ni duplicados),
  **supervisor** (mismos eventos, runner llamado una vez, `forbidden`), `POST` 201/401/422/503.
- `scripts/agent_chat_ws_probe.py`: evidencia medible contra la API real (§5).
- Verificación manual con capturas: [`manual-verification.md`](manual-verification.md).

---

## 13. Preguntas de diseño

### Pregunta 1

> ¿Por qué esta funcionalidad necesita WebSockets y no te alcanza con lo que construiste en la Parte 1? ¿Qué parte del requisito obliga específicamente a un canal bidireccional?

Lo que obliga es la **interrupción a mitad de respuesta**. El SSE de la Parte 1 es solo
servidor → cliente: vale para avisar de una RFP nueva, porque el cliente no tiene nada que
decir mientras escucha. Aquí el cliente tiene que enviar `interrupt_requested` (con el nuevo
texto) **mientras** el servidor sigue enviando `token_chunk` del mismo turno, y el servidor tiene
que procesarlo en ese momento para cortar el stream del modelo y abrir otro turno.

Con SSE habría que montar un segundo canal (`POST /interrupt`) y correlacionarlo a mano con el
stream: otra autenticación, otro orden y una carrera entre el `POST` y los tokens que ya están
saliendo. El WebSocket da los dos sentidos en **una sola conexión autenticada y ordenada**:
`user_message` e `interrupt_requested` suben por el mismo socket por el que bajan los tokens, el
servidor responde a cada comando con sus eventos (`generation_interrupted`, eco del nuevo
`user_message`, `generation_started`…) en el mismo orden en que ocurren, y los errores del
comando (`chat_error`) vuelven por la conexión que lo envió. Además, el handshake liga la
conexión a una conversación concreta (`/sessions/{session_id}/ws`), y con eso se rehidrata al reconectar.

### Pregunta 2

> Si más de un cliente está suscrito a la misma sesión de chat (por ejemplo, un supervisor observando la conversación en vivo), ¿cómo te aseguras de que todos reciban los mismos eventos sin duplicar las llamadas al agente?

Separando productor y consumidores:

- **Productor único por sesión:** `ChatTurnManager` (singleton del proceso) tiene como mucho una
  generación activa por `session_id` (`active[session_id]`, registrada antes de cualquier `await`).
  Solo él llama a `run_agent`, una vez por turno, en un hilo. **El handler WebSocket nunca llama al
  agente**: solo pasa los comandos del dueño al gestor. Un segundo `user_message` con un turno
  activo se rechaza (`generation_in_progress`) en lugar de lanzar otra corrida.
- **Pub/sub por sesión:** el gestor publica cada evento una vez en `chat.<session_id>`
  (`ChatPubSub`) y cada conexión suscrita, del dueño o de un supervisor, tiene su propia cola y
  recibe la misma secuencia en el mismo orden (`sequence` de cada `token_chunk` y `message_id`).
  Una conexión lenta no frena a las demás: si su cola se llena, se cierra con 1013 y rehidrata.
- **Permisos:** el supervisor (`admin`/`manager`) se conecta con su JWT y `?session=<id>`
  («Observando»); si envía algo recibe `chat_error forbidden`, así que no puede lanzar turnos.
- **Desacople de la conexión:** el turno no pertenece a ningún socket. Si el dueño se desconecta,
  sigue y se persiste, y quien se conecte después recibe el `session_snapshot` con el texto ya generado.

El test `test_owner_and_supervisor_receive_the_same_events_and_the_agent_runs_once` lo
demuestra: dueño y manager conectados reciben listas de eventos idénticas y el runner se llama
**una** vez. El log de la API muestra una sola línea `agent run_id=…` por turno.

### Pregunta 3

> ¿Cómo separaste el abort del stream (parar tokens) de LangGraph HITL interrupt() (pausa de grafo), si usaste lo segundo? ¿Qué pasa con el mensaje parcial del asistente y con el siguiente turno?

**No usamos `interrupt()`.** `interrupt()` pausa el grafo en un nodo para que un humano decida y
lo reanude con un `Command` sobre el mismo checkpoint (lo usamos así en la aprobación de RFPs).
Aquí no hay nada que reanudar: el usuario descarta la respuesta y pide otra cosa. Por eso el
abort es otra cosa:

- `cancel_event` (`threading.Event` en `config["configurable"]`), que comprueban el bucle de deltas
  de `generate_answer` y `run_agent` entre chunks de `graph.stream`;
- `stream.close()` sobre la respuesta del modelo (el SDK cierra la conexión HTTP: el modelo deja de
  enviar tokens) y `GenerationCancelled`;
- `run_agent` sale del bucle sin ejecutar más nodos, guarda el trace como `interrupted` y lanza
  `AgentRunCancelled(run_id)`.

El abort se detecta en el siguiente delta del modelo; una llamada del enrutador ya en vuelo
termina antes de cortar, y mientras tanto no se reenvía ningún token. Se mide como **cero
`token_chunk` del `message_id` viejo después de `generation_interrupted`** (tests y sonda).

**El mensaje parcial** se guarda con exactamente el texto ya emitido y `status = "interrupted"`
(con el `run_id` de su trace), **nunca se borra ni se sobrescribe**, y aparece en el historial con
el badge «Interrumpido», también tras reconectar. La sesión pasa a `interrupted`.

**El siguiente turno** es un turno nuevo, no una reanudación. Con `new_input` se guarda y se
publica un `user_message` nuevo, la sesión vuelve a `active` y arranca otra corrida del agente
con **otro `message_id`** (y otro `run_id`/`thread_id`), cuya pregunta es `new_input`. No hereda el
estado del grafo del turno cortado (§6). Si llega `interrupt_requested` sin `new_input`, la sesión
queda `interrupted` hasta el siguiente `user_message`.
