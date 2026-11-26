# Verificación manual — chat de soporte por WebSocket: tokens en vivo, abort y reconexión

Guion de la prueba del WebSocket `/agent/chat/sessions/{session_id}/ws` y de la página
**Chat de soporte** del backoffice. La ejecutó Marisin. El diseño está en
[`chat-ws-design.md`](chat-ws-design.md) y las capturas (`chatws-*.png`) en [`evidence/`](evidence/).

**Entorno:** Codespaces, rama `feature/websocket-chat`, 2026-11-26. LLM real de 4Geeks,
Supabase (PostgreSQL) y Qdrant.

**Preparación:**

```bash
# Una vez: tablas del chat en Supabase (SQL Editor) — o dejar que create_all las cree sin checks ni RLS
#   services/sql/006_chat_sessions.sql
# Dependencias locales (Qdrant para el RAG, Redis para la memoria)
docker compose up -d qdrant redis
# Terminal 1 — API (raíz del repo)
python -m uvicorn services.api.main:app --port 8000 --timeout-graceful-shutdown 3
# Terminal 2 — backoffice en build de producción (en `dev` el HMR recarga la página al volver la red)
cd uis/backoffice && npm run build && npm run start
# Terminal 3 — sonda
export TRACKFLOW_TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"<usuario>","password":"<contraseña>"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

| Prueba | Resultado | Evidencia |
|---|---|---|
| `006_chat_sessions.sql` en Supabase y la consulta de verificación del final del fichero | ✅ `chat_messages` 8 columnas, `chat_sessions` 6 | `evidence/chatws-sql-tablas.png` |

**Leyenda:** ✅ comprobado con captura · 🧪 no ejecutado a mano: lo cubren los tests o la sonda (se indica cuáles).

**La métrica del abort** es **cero `token_chunk` del `message_id` viejo después de
`generation_interrupted`**. `dropped_after_abort` (log de la API) cuenta los tokens tardíos que
el gestor **descartó** porque ya iban hacia el event loop. Con el LLM real puede ser > 0 sin que
sea un fallo; solo es 0 de forma determinista con el runner falso de los tests.

**Tiempos medidos:** ~3,2 s entre `generation_started` y el primer token (enrutado + RAG) y
después **56 tokens en ~250 ms**, que llegan en paquetes (~200 tokens/s). Con esa velocidad una
persona no puede interrumpir a mitad de los tokens desde la UI: la **evidencia principal del abort
a mitad de respuesta es la sonda** (paso 4).

## 1. Sin token: cierre 4401 sin eventos

**Pasos:** `python scripts/agent_chat_ws_probe.py --no-token`

| Esperado | Resultado | Evidencia |
|---|---|---|
| `← cerrado con 4401 (unauthorized) tras 0 frames` y `resultado: close_code=4401 frames_before_close=0 → OK` | ✅ cerrado con 4401 (unauthorized) tras 0 frames, en 9,8 ms → OK | `evidence/chatws-probe-no-token.png` |
| En el log de uvicorn la línea `WebSocket /agent/chat/sessions/…/ws` no muestra el token | ✅ `"WebSocket /agent/chat/sessions/chat_…/ws?token=[redacted]" [accepted]` | `evidence/chatws-log-token-redactado.png` |

## 2. Tokens en vivo en «Chat de soporte»

**Pasos:** Backoffice → **Chat de soporte** → **Nueva conversación** (cliente `ecowear_usa`) →
pregunta de política (ventana de devolución). DevTools → Network → **WS** → Messages.

| Esperado | Resultado | Evidencia |
|---|---|---|
| La petición WS va a `/api/backend/agent/chat/sessions/<id>/ws?token=…` y responde `101 Switching Protocols` a través del proxy de Next; el indicador dice **Conectado** | ✅ «Conectado» y la fila `websocket` con 101 por `/api/backend` (JWT tapado en la captura) | `evidence/chatws-conectado.png` |
| El primer frame recibido es `session_snapshot` con los campos de `ChatSession` | ✅ `agent_id: first_line_cx`, `user_id: 1`, `client_id: ecowear_usa`, `status: active`, `messages: []`, `active_generation: null` | `evidence/chatws-snapshot.png` |
| En Messages: `user_message` (enviado) → eco `user_message` con `message_id` → `generation_started` → `token_chunk` con `sequence` 1, 2, 3… | ✅ en ese orden; ~3,2 s entre `generation_started` y el primer token y **56 tokens en ~250 ms**, en paquetes | `evidence/chatws-tokens-tiempos.png` |
| Cada `token_chunk` lleva `session_id`, `message_id`, `token` y `sequence` | ✅ `token_chunk` #56 desplegado | `evidence/chatws-tokens-en-vivo.png` |
| `generation_completed` con `answer`, `status` y `sources` | ✅ `status: answered`, `sources: ["rag"]` y el `answer` completo | `evidence/chatws-generation-completed.png` |

## 3. Interrumpir y redirigir (visto en la UI)

**Cómo se hizo:** a ~200 tokens/s no da tiempo a interrumpir a mano a mitad de los tokens. La
interrupción la envió la sonda del paso 4 (sonda 1) con el navegador **conectado a la misma
sesión** (`chat_4e16b22df7a1`) y sin enviar nada desde él: así se ve el efecto en la UI y en los
frames de una segunda conexión.

| Esperado | Resultado | Evidencia |
|---|---|---|
| En Messages, `generation_interrupted` (`status: "interrupted"`) → `user_message` con el nuevo texto → `generation_started` con **otro** `message_id` → tokens → `generation_completed` | ✅ `token_chunk` 1–5 de `msg_15a42e07564d` → `generation_interrupted` → `user_message` → `generation_started` `msg_e0851ad7901d` → `token_chunk` → `generation_completed` | `evidence/chatws-interrupcion-ws-frames.png` |
| **Ningún `token_chunk` del `message_id` viejo después de `generation_interrupted`** | ✅ ningún frame de `msg_15a42e07564d` tras el corte | `evidence/chatws-interrupcion-ws-frames.png` |
| El mensaje cortado queda con el badge ámbar **Interrumpido** y el texto parcial; debajo, el nuevo mensaje del usuario y la respuesta nueva | ✅ parcial «El proceso estándar es el» con «Interrumpido», el `user_message` de redirección y la respuesta nueva | `evidence/chatws-interrupcion-ui.png` |
| Trace del turno cortado: `status: interrupted`, `cancelled.stream_closed: true` y sin `compose_answer` | ✅ `data/agent_traces/707c3005-….json`: `conversation_id: chat_4e16b22df7a1`, `status: interrupted`, `cancelled: {tokens_sent: 5, stream_closed: true}`, path `receive_question → route_question → retrieve → generate_answer`, `error: null` | `evidence/chatws-interrupcion-trace.png` |
| **Detener** (sin texto) desde la UI solo interrumpe | 🧪 no ejecutado a mano. Lo cubren `test_interrupting_without_new_input_leaves_the_session_interrupted` y la variante sin `--new-input` de la sonda | — |

## 4. Abort a mitad de los tokens con la sonda (evidencia principal)

**Pasos:**

```bash
python scripts/agent_chat_ws_probe.py --session chat_4e16b22df7a1 \
  --question "<pregunta de política>" --interrupt-after 5 --new-input "<redirección>"
```

La sonda envía `interrupt_requested` **en cuanto recibe** el `token_chunk` #5, antes de leer
otro frame, e imprime cada evento con su hora.

| Esperado | Sonda 1 (`new_input` que no es de política) | Sonda 2 (`new_input` de política) | Evidencia |
|---|---|---|---|
| `tokens_before_interrupt = 5` | ✅ 5 | ✅ 5 | `evidence/chatws-probe-interrupt.png`, `evidence/chatws-probe-interrupt-2.png` |
| `tokens_in_flight` (entre el envío y `generation_interrupted`) | ✅ 0 | ✅ **38**: el proxy del LLM entregó los tokens 6–43 en el mismo milisegundo | ídem |
| `interrupt_to_generation_interrupted_ms` | ✅ 514 | ✅ 557 | ídem |
| **`tokens_after_interrupt_for_old_message = 0`** | ✅ **0** | ✅ **0** | ídem |
| Turno nuevo con otro `message_id` | ✅ `msg_15a42e07564d` → `msg_e0851ad7901d`, `status: no_context` (el `new_input` no era una pregunta de política) | ✅ `msg_bd3adaf34b04` → `msg_5f33bd7b48ce`, `answered`, 53 tokens | ídem |
| Log de la API del turno cortado: `cancelled … stream_closed=True` | — (antes del fix de logs) | ✅ `agent run_id=5be685bd-… cancelled tokens_sent=43 stream_closed=True path=… → generate_answer`, `chat session=… message_id=msg_bd3adaf34b04 cancelled … tokens_sent=43 stream_closed=True dropped_after_abort=…`, `interrupted tokens_published=43` y el turno nuevo `completed … tokens=53` | `evidence/chatws-interrupcion-log.png` |

La sonda 2 muestra por qué la métrica es la de después de `generation_interrupted`: a ~200
tokens/s, y con el proxy entregando en paquetes, decenas de tokens pueden estar ya en camino
cuando sale la interrupción. Esos llegan **antes** de `generation_interrupted` (y cuentan como
emitidos: `tokens_sent=43`, el parcial guardado los incluye). Después del corte no llega ninguno.

## 5. Corte de red: backoff y rehidratación

🧪 **No ejecutado a mano.** Lo cubren:

- **Backoff y rehidratación con la API real**: el paso 6 (reinicio de la API). Los retardos
  0,9 → 2,0 → 3,2 s y el `session_snapshot` desde PostgreSQL son el mismo camino de reconexión
  de `chat-ws.ts`; `offline`/`online` solo cambian lo que dispara el cierre y la espera.
- **Rehidratación sin huecos ni duplicados**: `test_reconnecting_rehydrates_the_history_including_the_interrupted_message`
  y `test_reconnecting_mid_turn_resumes_from_the_partial_text_without_gaps_or_duplicates` de
  `tests/test_agent_chat_ws.py`.

| Esperado | Resultado | Evidencia |
|---|---|---|
| Offline → «Reconectando en N s… (intento k)» con retardos crecientes; online → reconecta ya, «Rehidratando…» y **Conectado** | 🧪 cubierto por el paso 6 y los tests de reconexión | — |
| El historial está intacto, incluido el mensaje **Interrumpido**, sin duplicados | 🧪 cubierto por el paso 6 (14 mensajes con los dos «Interrumpido») y los tests de reconexión | — |

## 6. Reinicio de la API y vuelta a la misma sesión

**Pasos:** parar uvicorn (Ctrl+C) y volver a arrancarlo con `--timeout-graceful-shutdown 3`.

| Esperado | Resultado | Evidencia |
|---|---|---|
| Mientras la API está caída, reintentos con backoff | ✅ `[chat-ws] conexión perdida (código 1012)` → reconectando en 0,9 s (intento 1), 2,0 s (2), 3,2 s (3) | `evidence/chatws-reinicio-backoff.png` |
| Un cierre 4401 no se reintenta | ✅ el JWT del navegador había caducado (60 min) → `cerrado con 4401 (unauthorized): no se reintenta` y la UI muestra «Sesión caducada · Iniciar sesión» | `evidence/chatws-reinicio-backoff.png` |
| Al volver, `session_snapshot` **desde PostgreSQL** con los mismos mensajes y estados | ✅ log `chat session=chat_4e16b22df7a1 conectado user_id=1 dueño mensajes=10` tras el reinicio; tras volver a iniciar sesión, `session_snapshot` con 14 mensajes, «Conectado» y el historial completo con los dos mensajes **Interrumpido** | `evidence/chatws-interrupcion-log.png`, `evidence/chatws-reinicio-snapshot.png` |
| La página vuelve a la **misma** sesión (`localStorage`, clave `trackflow.chat_session_id`) | ✅ tras el login, la página reabrió `chat_4e16b22df7a1` desde `localStorage` | `evidence/chatws-reinicio-snapshot.png` |

## 7. Supervisor observando en vivo

🧪 **No ejecutado a mano** con un usuario `admin`/`manager` en otra ventana. Lo cubren:

- `test_owner_and_supervisor_receive_the_same_events_and_the_agent_runs_once`
  (`tests/test_agent_chat_ws.py`): dueño y `manager` conectados reciben listas de eventos
  idénticas, el runner se llama **una** vez y el observador que escribe recibe `chat_error forbidden`.
  `test_another_user_closes_with_4403_but_a_manager_can_join` cubre el 4403 y la entrada del `manager`.
- Con la API real: la sonda y el navegador conectados a la misma sesión (pasos 3 y 4). El
  navegador vio los mismos tokens, el corte y el turno nuevo sin enviar nada
  (`evidence/chatws-interrupcion-ui.png`), y el agente se llamó una vez por turno.

| Esperado | Resultado | Evidencia |
|---|---|---|
| El supervisor ve «Observando», con el input desactivado, y los mismos tokens que el dueño | 🧪 tests de supervisor; dos conexiones reales a la misma sesión en el paso 3 | `evidence/chatws-interrupcion-ui.png` |
| Una sola corrida del agente por turno con dos conexiones | 🧪 test de supervisor (runner llamado una vez); en el log del paso 4, una línea `agent run_id=…` por turno | `evidence/chatws-interrupcion-log.png` |
| Un `user` que no es el dueño → 4403 sin reintentos | 🧪 `test_another_user_closes_with_4403_but_a_manager_can_join` | — |

## Observaciones

- **a) Qdrant parado al empezar.** El Codespace se había reiniciado: el primer turno falló en el
  nodo `retrieve`, el mensaje quedó con `status: error` y la UI mostró «El agente no ha podido
  completar la respuesta» sin colgarse (`chat_error agent_unavailable`). Se arrancó con
  `docker compose up -d qdrant redis` (añadido a la preparación).
- **b) Velocidad del modelo.** El LLM de 4Geeks va a ~200 tokens/s y el proxy entrega en
  paquetes (sonda 2: los tokens 6–43 en el mismo milisegundo). Desde la UI una persona no
  interrumpe a mitad de los tokens: la sonda es la evidencia principal del abort.
- **c) Logs en consola.** Al principio los INFO de `api.agent.chat` y `agent.runner` no salían en la
  consola de uvicorn (sin handler). Se corrigió durante la verificación en `1a1905d`
  (`fix: muestra en consola los logs del chat y del runner`). Por eso la sonda 1 no tiene captura
  del log y la sonda 2 sí.
- **d) JWT caducado durante la prueba de reinicio.** El token del navegador dura 60 min. Al
  reconectar tras el reinicio, el servidor cerró con 4401 y el cliente dejó de reintentar, como
  se esperaba. Tras volver a iniciar sesión, la sesión se rehidrató desde PostgreSQL.

## Conclusión

- **Tokens en vivo:** ✅ del stream real del modelo, numerados con `sequence` y con `generation_completed` como texto definitivo.
- **Auth:** ✅ 4401 sin frames, sin token; el token se redacta en los logs.
- **Abort real a mitad de los tokens:** ✅ en las dos sondas, `tokens_after_interrupt_for_old_message = 0`; `stream_closed=True` en el log y en el trace; el parcial se conserva como «Interrumpido» y el turno nuevo tiene otro `message_id`.
- **Rehidratación:** ✅ desde PostgreSQL tras reiniciar la API, con backoff, sin reintentos ante 4401 y vuelta a la misma sesión desde `localStorage`.
- **Corte de red offline (paso 5) y supervisor en otra ventana (paso 7):** 🧪 no se hicieron a mano. Los cubren los tests de reconexión y de supervisor, el reinicio de la API y las dos conexiones reales a la misma sesión.
