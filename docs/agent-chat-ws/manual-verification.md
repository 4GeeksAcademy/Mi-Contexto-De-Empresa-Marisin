# Verificación manual — chat de soporte por WebSocket: tokens en vivo, abort y reconexión

Guion de la prueba del WebSocket `/agent/chat/sessions/{session_id}/ws` y de la página
**Chat de soporte** del backoffice. Lo ejecuta Marisin. El diseño está en
[`chat-ws-design.md`](chat-ws-design.md) y las capturas (`chatws-*.png`) en [`evidence/`](evidence/).

**Entorno:** Codespaces, rama `feature/websocket-chat`, 2026-11-26.

**Preparación:**

```bash
# Una vez: tablas del chat en Supabase (SQL Editor) — o dejar que create_all las cree sin checks ni RLS
#   services/sql/006_chat_sessions.sql
# Terminal 1 — API (raíz del repo)
python -m uvicorn services.api.main:app --port 8000 --timeout-graceful-shutdown 3
# Terminal 2 — backoffice en build de producción (en `dev` el HMR recarga la página al volver la red)
cd uis/backoffice && npm run build && npm run start
# Terminal 3 — sonda
export TRACKFLOW_TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"<usuario>","password":"<contraseña>"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

**Leyenda:** ✅ comprobado con captura · ☑️ comprobado, falta la captura · ⏳ pendiente.

**La métrica del abort** es **cero `token_chunk` del `message_id` viejo después de
`generation_interrupted`**. `dropped_after_abort` (log de la API) cuenta los tokens tardíos que
el gestor **descartó** porque ya iban hacia el event loop. Con el LLM real puede ser > 0 sin que
sea un fallo; solo es 0 de forma determinista con el runner falso de los tests.

**Tiempos de referencia (medidos en el navegador):** ~3,2 s desde el mensaje hasta el primer
token (enrutado + RAG) y después **56 tokens en ~250 ms** (~200 tokens/s). Con esa velocidad una
persona no puede interrumpir a mitad de los tokens desde la UI: la **evidencia principal del abort
a mitad de respuesta es la sonda** (paso 4). En la UI (paso 3) la interrupción realista llega durante
los ~3,2 s previos al primer token.

## 1. Sin token: cierre 4401 sin eventos

**Pasos:** `python scripts/agent_chat_ws_probe.py --no-token`

| Esperado | Resultado | Evidencia |
|---|---|---|
| `← cerrado con 4401 (unauthorized) tras 0 frames` y `resultado: close_code=4401 frames_before_close=0 → OK` | ⏳ | `evidence/chatws-probe-no-token.png` |
| En el log de uvicorn la línea `WebSocket /agent/chat/sessions/…/ws` no muestra ningún token (con token, debe verse `token=[redacted]`) | ⏳ | `evidence/chatws-api-log-redacted.png` |

## 2. Tokens en vivo en «Chat de soporte»

**Pasos:** Backoffice → **Chat de soporte** → **Nueva conversación** (cliente `ecowear_usa`) →
preguntar «¿Cuál es la ventana de devolución en España?». DevTools → Network → **WS** → Messages.

| Esperado | Resultado | Evidencia |
|---|---|---|
| La petición WS va a `/api/backend/agent/chat/sessions/<id>/ws?token=…` y responde `101 Switching Protocols` a través del proxy de Next | ☑️ 101 por `/api/backend` | `evidence/chatws-ui-network-101.png` |
| El indicador dice **Conectado**. El primer frame recibido es `session_snapshot` | ☑️ el snapshot llega primero | `evidence/chatws-ui-conectado.png` |
| La respuesta se escribe token a token con el cursor ▍. En Messages: `user_message`, `generation_started`, `token_chunk` con `sequence` 1, 2, 3… y `generation_completed` con `answer` | ☑️ **56 tokens en ~250 ms**, tras **~3,2 s** de enrutado + RAG; los `token_chunk` llegan del stream del modelo | `evidence/chatws-ui-tokens-network.png` |

## 3. Interrumpir desde la UI y redirigir

**Pasos:** enviar una pregunta y, **antes de que termine** (en la práctica, durante los ~3,2 s
previos al primer token), escribir «espera, quiero hacer una devolución, no rastrear el pedido»
y pulsar **Redirigir** (Enter). Mirar Messages y el log de la API.

| Esperado | Resultado | Evidencia |
|---|---|---|
| En Messages, `interrupt_requested` (enviado) → `generation_interrupted` (`status: "interrupted"`) → `user_message` con el nuevo texto → `generation_started` con **otro** `message_id` → tokens → `generation_completed` | ⏳ | `evidence/chatws-ui-interrupt-network.png` |
| **Ningún `token_chunk` del `message_id` viejo después de `generation_interrupted`** | ⏳ | `evidence/chatws-ui-interrupt-network.png` |
| El mensaje cortado queda con el badge ámbar **Interrumpido** (con el texto parcial, o vacío si se cortó antes del primer token); debajo, el nuevo mensaje del usuario y la respuesta nueva | ⏳ | `evidence/chatws-ui-interrumpido.png` |
| Log de la API: `agent run_id=… cancelled tokens_sent=… stream_closed=…` y `chat session=… cancelled … dropped_after_abort=…`. Si el corte llegó antes de llamar al modelo, `stream_closed=False` y `tokens_sent=0`. `dropped_after_abort` puede ser > 0 (no es un fallo) | ⏳ | `evidence/chatws-api-log-cancel.png` |
| **Detener** (sin texto) solo interrumpe: badge «Interrumpido» y la sesión pasa a `interrupted` | ⏳ | — |

## 4. Abort a mitad de los tokens con la sonda (evidencia principal)

**Pasos:**

```bash
python scripts/agent_chat_ws_probe.py --question "¿Cuál es la ventana de devolución estándar en España?" \
  --interrupt-after 5 --new-input "espera, quiero hacer una devolución, no rastrear el pedido"
```

La sonda envía `interrupt_requested` **en cuanto recibe** el `token_chunk` #5, antes de leer
otro frame, e imprime cada evento con su hora.

| Esperado | Resultado | Evidencia |
|---|---|---|
| `→ interrupt_requested tras el token #5 …` justo después del `token_chunk … #5` | ⏳ | `evidence/chatws-probe-interrupt.png` |
| `tokens_before_interrupt = 5`; `tokens_in_flight = k` (los que ya estaban en la red o en la cola entre el envío y `generation_interrupted`: es normal que haya alguno a ~200 tokens/s) e `interrupt_to_generation_interrupted_ms` | ⏳ | `evidence/chatws-probe-interrupt.png` |
| **`tokens_after_interrupt_for_old_message = 0`**, `new_message_id = msg_…` distinto del viejo y `fin: respuesta del turno nuevo completa` (código de salida 0) | ⏳ | `evidence/chatws-probe-interrupt.png` |
| Log de la API del mismo turno: `cancelled … stream_closed=True` | ⏳ | `evidence/chatws-api-log-cancel.png` |

Variante sin turno nuevo: `--interrupt-after 5` sin `--new-input` → la sonda escucha 2 s más
tras `generation_interrupted` y debe seguir dando `tokens_after_interrupt_for_old_message = 0`.
Si la respuesta termina antes de llegar la interrupción (`fin: … terminó antes …` o
`nothing_to_interrupt`), repetir con un `--interrupt-after` menor.

## 5. Corte de red: backoff y rehidratación

**Pasos:** con la conversación abierta, DevTools → Network → **Offline**. Esperar ~60 s y
volver a **No throttling**.

| Esperado | Resultado | Evidencia |
|---|---|---|
| El indicador pasa a «Reconectando en N s… (intento k)». En la consola: `[chat-ws] el navegador está offline…` y `[chat-ws] reconectando en …` con retardos crecientes: ~1, 2, 4, 8, 16 s, tope 30 s, ±20 % de jitter | ⏳ | `evidence/chatws-reconexion-backoff.png` |
| Al volver online: `[chat-ws] de vuelta online: se reconecta ya`, «Rehidratando…», `[chat-ws] session_snapshot: N mensajes` y **Conectado** | ⏳ | `evidence/chatws-reconexion-snapshot.png` |
| El historial está intacto, incluido el mensaje **Interrumpido** del paso 3, sin duplicados | ⏳ | `evidence/chatws-reconexion-snapshot.png` |

## 6. Reinicio de la API y F5

**Pasos:** parar uvicorn (Ctrl+C) y volver a arrancarlo con `--timeout-graceful-shutdown 3`.
Después, recargar la página (F5).

| Esperado | Resultado | Evidencia |
|---|---|---|
| Mientras la API está caída, reintentos con backoff (`[chat-ws] conexión perdida (código …)`) | ⏳ | `evidence/chatws-reinicio-backoff.png` |
| Al volver, `session_snapshot` **desde PostgreSQL**: los mismos mensajes y estados que antes del reinicio | ⏳ | `evidence/chatws-reinicio-snapshot.png` |
| F5 vuelve a la **misma** sesión (el `session_id` está en `localStorage`, clave `trackflow.chat_session_id`) | ⏳ | — |

## 7. Supervisor observando en vivo

**Pasos:** otra ventana (incógnito) con un usuario `admin` o `manager` →
`/support-chat?session=<session_id>`. Desde la ventana del dueño, hacer una pregunta.

| Esperado | Resultado | Evidencia |
|---|---|---|
| La ventana del supervisor muestra **Observando** y el input desactivado | ⏳ | `evidence/chatws-supervisor.png` |
| Ve los mismos tokens en vivo que el dueño | ⏳ | `evidence/chatws-supervisor.png` |
| El log de la API muestra **una sola** línea `agent run_id=…` por turno, aunque haya dos conexiones | ⏳ | `evidence/chatws-supervisor-api-log.png` |
| Un usuario `user` que no es el dueño con `?session=<id>` → «Sin acceso a esta conversación» (cierre 4403, sin reintentos) | ⏳ | — |

## Observaciones

_(rellenar tras la prueba)_

## Conclusión

_(rellenar tras la prueba)_
