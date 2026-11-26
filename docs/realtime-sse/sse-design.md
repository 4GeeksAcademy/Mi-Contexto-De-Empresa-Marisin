# Notificaciones en tiempo real por SSE — diseño (Parte 1 de 2)

El equipo comercial de **Miguel Torres** (Commercial Director) se enteraba de una
RFP nueva revisando el dashboard por su cuenta. Ahora la página **RFPs** del
backoffice recibe un evento `rfp_ticket_created` en cuanto el clasificador da
el documento por RFP válida, y pinta el aviso y la fila **sin recargar**.

No se rediseña el sistema de RFPs: solo se le añade la notificación. En esta
capa no hay ninguna llamada a modelos ni a agentes.

## 1. Arquitectura

```text
POST /rfp/tickets ──► BackgroundTasks (threadpool)
                        │
                        ▼
  data/pipelines/rfp_intake/runner.py  process_ticket()
      convert → classify ──(no es RFP)──► discard            (no emite nada)
                  │
                  └─(RFP válida)─► extract_metadata ─► store.save_metadata()
                                                        │
                                                        ▼
                               events.emit("rfp_ticket_created", payload)
                                   data/pipelines/rfp_intake/events.py
                                                        │  listener registrado al importar
                                                        ▼
                     services/realtime/router.py  forward_pipeline_event()
                         valida con RfpTicketCreatedEvent (extra="forbid")
                                                        │
                                                        ▼
                     services/realtime/broker.py  EventBroker.publish()
                         dedupe por ticket_id · buffer de 200 · id "{boot}-{seq}"
                         loop.call_soon_threadsafe → asyncio.Queue por conexión
                                                        │
                                                        ▼
             GET /realtime/events  (JWT del backoffice, StreamingResponse)
                                                        │
                                                        ▼
            proxy de Next  /api/backend/:path*  (next.config.ts)
                                                        │
                                                        ▼
    uis/backoffice/src/lib/sse.ts  connectSse()  fetch + ReadableStream
    uis/backoffice/src/lib/rfp-notifications.ts  useRfpNotifications()
    uis/backoffice/src/app/rfp/page.tsx  aviso «Nueva RFP» + upsert de la fila
```

- **Desacople.** El pipeline no importa FastAPI ni `services.*`. Solo llama a
  `events.emit()`, que nunca lanza: si un listener falla, se registra en el log
  y el ticket sigue su curso. Cuando no hay listener (por ejemplo,
  `scripts/rfp_intake_run.py` en su propio proceso), `emit()` no hace nada.
- **Hilos.** El pipeline corre en el threadpool de `BackgroundTasks`. Cada
  conexión guarda el event loop en el que se abrió, y `publish()` le entrega el
  evento con `loop.call_soon_threadsafe`. El reparto del replay y el registro
  del suscriptor se hacen bajo el mismo lock que `publish()`. Así un evento
  llega por replay o por la cola, nunca por las dos vías ni por ninguna.
- **Backpressure.** Cada conexión tiene una cola de 100 eventos. Si se llena,
  el broker cierra esa conexión y el cliente se recupera al reconectar.

## 2. Cuándo se emite

Se emite en `runner.process_ticket`, justo después de `store.save_metadata(...)`
del nodo `extract_metadata`. En ese momento:

- el ticket ya está clasificado como **RFP válida** y el flujo empieza a
  procesarlo;
- el estado sigue siendo `analizando`;
- ya existen `client_name`, `client_country` y `services_requested`.

Emitirlo en el `POST` daría metadatos vacíos y avisaría también de PDF que
luego se descartan. Un documento descartado **nunca** emite (lo cubren los
tests y la captura `sse-ui-nueva-rfp.png`).

## 3. Wire

Al abrir una conexión nueva (sin `Last-Event-ID`):

```text
retry: 3000
id: 1795708225-0
: connected

```

Este frame es real: aparece en `evidence/sse-curl-stream.png`. El `id:` sin
`data:` no dispara ningún evento, pero le da al cliente una posición desde la
que reanudar aunque se corte antes de recibir nada.

Un evento:

```text
id: 1795708225-1
event: rfp_ticket_created
data: {"ticket_id":5,"rfp_id":"d9fea3c8-e4b4-4ac7-922c-9f20087b3942","client_name":"ModaViva","client_country":"Spain","services_requested":["warehousing","reverse_logistics"],"status":"analizando","created_at":"2026-11-26T17:00:58Z","stage":"orquestando","original_filename":"b393753c-35d4-477e-9f58-c7fb0afdb353.pdf"}

```

Los datos son los del ticket #5 de `evidence/sse-ui-nueva-rfp.png`. El `id`
de este ejemplo es ilustrativo.

- Una sola línea `data:` con **JSON plano**: no hay sobre `{"event", "data"}`,
  porque el nombre del evento ya va en `event:`.
- Los campos son los 7 que pide el ticket (`ticket_id`, `rfp_id`,
  `client_name`, `client_country`, `services_requested`, `status`,
  `created_at`). Se añaden `stage` y `original_filename`, que ya existen en
  `RfpTicketSummary`, para pintar la fila sin pedir el ticket. No se envían
  ni el documento ni las secciones por departamento.
- Sin eventos, cada `SSE_KEEPALIVE_SECONDS` (15 por defecto) se envía el
  comentario `: keep-alive`.
- Si el servidor no puede reanudar, se envía
  `event: resync` con `data: {"reason":"server_restarted" | "events_expired" | "invalid_last_event_id"}`.

### Por qué `analizando` y no `analyzing`

El ejemplo del enunciado usa `"analyzing"`, `"tkt_0225"` y `"US"`, pero la
restricción es que los nombres coincidan con los del sistema de RFPs. El
nuestro persiste otros valores:

| Campo | Valor real | Dónde está definido |
|---|---|---|
| `status` | `analizando` | `STATUS_ANALYZING` en `data/pipelines/rfp_intake/config.py` |
| `ticket_id` | entero | `RfpTicketSummary.ticket_id: int` |
| `rfp_id` | UUID | `uuid4()` en `data/pipelines/rfp_intake/intake.py` |
| `client_country` | `"United States"` o `"Spain"` | `Country` en `data/pipelines/rfp_intake/schemas.py` |
| `services_requested` | `warehousing`, `last_mile`, `reverse_logistics` | `Service` en ese mismo fichero |

## 4. Endpoint y headers

`GET /realtime/events` (`services/realtime/router.py`):

- **Autenticación.** Exige `Depends(get_current_user)`, el mismo JWT
  (`Authorization: Bearer`) que el resto del backoffice. Sin token o con un
  token inválido responde **401** antes de abrir el stream (captura
  `sse-curl-401.png`).
- **Headers.**

  | Header | Valor |
  |---|---|
  | `Content-Type` | `text/event-stream; charset=utf-8` |
  | `Cache-Control` | `no-cache, no-transform` |
  | `Connection` | `keep-alive` |
  | `X-Accel-Buffering` | `no` |

  `no-transform` y `X-Accel-Buffering: no` evitan que un proxy (el de Next,
  nginx) comprima o acumule el stream. Las capturas `sse-curl-stream.png` y
  `sse-ui-network-fetch.png` muestran estos headers a través del proxy de
  Codespaces.
- **Genérico.** El endpoint sirve cualquier nombre de evento del broker. El
  caso opcional (`sla_threshold_alert`, `ticket_escalated_to_senior`) no se
  implementa en esta entrega, pero cabría sin tocar el endpoint.
- **Contrato de rutas.** Pasa de 51 a 52. Este stream es la única ruta sin
  `response_model` que no es un 204, y queda en `DOCUMENTED_STREAM_ENDPOINTS`.

## 5. Recuperación y dedupe

**Estrategia: `Last-Event-ID` y replay corto, con `resync` de respaldo.**

1. Cada evento lleva `id: {boot_id}-{seq}`. `boot_id` es el epoch de arranque
   del proceso y `seq` es correlativo.
2. El cliente guarda el último `id:` recibido, incluido el del frame de
   apertura y el del `resync`. Al reconectar lo envía en el header
   `Last-Event-ID`.
3. El servidor responde según ese id:
   - **Mismo arranque y aún en el buffer** (últimos 200 eventos): reenvía solo
     los posteriores.
   - **Otro arranque, ya fuera del buffer o mal formado:** envía
     `event: resync` con su `id:` actual. El cliente hace **un**
     `GET /rfp/tickets` y sigue con el stream.

Ningún ticket se pierde en silencio: o llega por replay o lo trae el refetch.

**Dedupe en dos niveles:**

- **Servidor.** Un solo `rfp_ticket_created` por `ticket_id` en la vida del
  proceso. Reprocesar un ticket no vuelve a notificar.
- **Cliente.** Un `Set<number>` con los `ticket_id` ya notificados, y la lista
  se actualiza por `ticket_id` (upsert). Nunca aparecen dos filas ni dos avisos
  para el mismo ticket. Tras un `resync` solo se avisa de las RFP válidas (ya
  con cliente) que no estaban en la lista ni se habían notificado.

## 6. Cliente (`fetch` + `ReadableStream`)

El cliente SSE nativo del navegador no permite enviar `Authorization`, así que
`connectSse()` usa:

- `fetch` con `Accept: text/event-stream`, `Authorization: Bearer`,
  `Last-Event-ID` y `cache: "no-store"`;
- `response.body.getReader()` y `TextDecoder`;
- un parser de frames según WHATWG: `event`, `data` multilínea, `id`, `retry`,
  comentarios, `\r\n` partido entre chunks y BOM inicial.

**Reconexión:**

- **Backoff:** 1 s, 2 s, 4 s, 8 s, 16 s, con un máximo de 30 s y jitter de
  ±20 % (es decir, hasta 36 s; en la verificación: 1,0 → 2,3 → 3,6 → 7,5 →
  16,9 → 36,0 s). Vuelve a 1 s tras una conexión correcta. El `retry: 3000` del servidor
  es para clientes SSE nativos; este cliente sigue su backoff.
- **401:** no reintenta. El indicador pasa a «Sesión caducada».
- **Vigilancia de la conexión:**
  - si en 45 s no llega ni un byte (3 keep-alives), corta la conexión y
    reconecta;
  - el evento `offline` del navegador la corta al momento;
  - al volver `online` se reintenta sin esperar al final del retardo.
- **Logs:** en consola, con el prefijo `[sse]`, se registran cada
  (re)conexión, el `Last-Event-ID` enviado y el retardo del backoff. Sirven de
  evidencia.
- **Cierre:** se aborta con `AbortController` al desmontar la página. En
  desarrollo, React monta dos veces y por eso aparecen dos «conectando» en la
  consola.

## 7. UI

En `uis/backoffice/src/app/rfp/page.tsx`:

- **Indicador de conexión:** «En directo», «Reconectando en N s… (intento k)»
  o «Sesión caducada».
- **Aviso «Nueva RFP»:** banda esmeralda con borde lateral, que se puede
  descartar. Muestra `#ticket_id`, cliente, país, servicios, `rfp_id` y
  «requiere procesamiento». Es visualmente distinto de los mensajes de la
  página.
- **Fila nueva:** se resalta con un anillo y la etiqueta «Nuevo», que
  desaparece al abrir el ticket.
- **Sin refetch por evento:** el evento hace un upsert local de la fila. Si un
  refetch empezó antes de que llegara el evento, no borra la fila que trajo el
  evento.
- **Polling:** se mantiene **solo** para seguir el progreso de los tickets que
  ya están en marcha (análisis, borradores, aprobaciones) y se para cuando no
  hay trabajo. Los tickets nuevos se descubren por SSE.

## 8. Límites

- **Un solo proceso.** El broker vive en memoria: con varios workers de
  uvicorn o varias réplicas, un evento solo llega a las conexiones del proceso
  que ejecutó el pipeline. Ver la pregunta 1.
- **Reinicio de la API.** Al reiniciar se pierden el buffer y el registro de
  dedupe del servidor. El `resync` y el dedupe del cliente cubren ese hueco.
- **Cierre de uvicorn.** Los streams abiertos no terminan solos, así que
  Ctrl+C se queda esperando a que se cierren. Hay que arrancar la API con
  `--timeout-graceful-shutdown 3`: pasados 3 s, uvicorn cancela los streams y
  los clientes reconectan contra el nuevo proceso (`resync`). En producción,
  el `stopTimeout` del contenedor debe ser mayor que ese valor.
- **Recargas en desarrollo.** Con `npm run dev`, Next recarga la página al
  volver la red y la conexión empieza sin `Last-Event-ID`. El replay solo se
  aprecia con `npm run build` y `npm run start`.
- **Primera carga.** Si un ticket se crea entre la primera carga de la lista y
  la apertura del stream, no hay replay porque la conexión es nueva. Aparece
  en el siguiente polling o al pulsar «Actualizar».

## 9. Tests

- **`tests/test_realtime_sse.py`** (17 tests):
  - 401 sin token o con token inválido; un JWT real abre el stream;
  - headers;
  - wire: evento con nombre, campos exactos, `status == "analizando"`,
    `ticket_id` entero y sin sobre;
  - replay por `Last-Event-ID`;
  - `resync` por reinicio, por id mal formado o del futuro, y por buffer
    agotado;
  - dedupe por `ticket_id`;
  - keep-alive;
  - la conexión deja de estar suscrita al cerrarse;
  - entrega en vivo desde otro hilo.
- **`tests/pipelines/test_rfp_ticket_created_event.py`** (5 tests):
  - una RFP válida emite un único evento, ya con `client_name`, y el payload
    valida contra el esquema;
  - un documento descartado no emite;
  - un listener que lanza no rompe el pipeline, y tampoco un fallo del store
    al notificar.

## 10. Preguntas de diseño

**1. Si dos personas del equipo comercial abren el dashboard al mismo tiempo, ¿cada conexión SSE debería ser independiente o deberían compartir alguna capa intermedia? ¿Qué pasaría si 50 personas lo abren a la vez?**

Las dos cosas, cada una en su nivel.

**La conexión es independiente.** Cada pestaña abre su propio
`GET /realtime/events` con su JWT, y tiene su propia `asyncio.Queue(maxsize=100)`
y su propia posición (`Last-Event-ID`). Si un cliente es lento o se le corta la
red, eso solo le afecta a él: su cola se llena, el broker lo desconecta y se
recupera al reconectar. Nunca frena a los demás.

**El origen del evento es compartido.** Todas las conexiones cuelgan de una
capa intermedia, el `EventBroker`:

- el pipeline emite **una vez** por ticket, sin saber cuántas personas
  escuchan;
- el broker hace el fan-out a N colas;
- el buffer de replay y el dedupe por `ticket_id` son comunes.

Sin esa capa, cada conexión tendría que consultar la base de datos por su
cuenta (polling encubierto), o el pipeline tendría que conocer a los clientes.

**Con 50 personas a la vez, en un solo proceso uvicorn:**

- **Conexiones.** Son 50 conexiones HTTP de larga duración. Cada una es una
  corrutina dormida y una cola vacía.
- **Tráfico en reposo.** Unos 50 `: keep-alive` cada 15 s, de pocos bytes.
- **Un evento.** Una RFP nueva supone 50 `put_nowait` y 50 escrituras de
  unos 400 B. Es trivial frente a lo que tarda el propio pipeline.
- **Proxy de Codespaces.** Cabe de sobra en su límite. La cabecera de la
  captura de Network indica `ClientConnectionsPerPort: max 1000`.
- **Reinicio de la API.** Las 50 conexiones reconectan a la vez. El jitter de
  ±20 % del backoff las reparte y cada una hace **un** `GET /rfp/tickets` por
  el `resync`: 50 lecturas de la lista una sola vez, no cada 3 s como el
  polling.

**Puntos a vigilar:**

- **Varias pestañas de una misma persona por HTTP/1.1.** El navegador permite
  6 conexiones por origen, y cada pestaña consume una. Con HTTP/2 (el túnel
  HTTPS de Codespaces) se multiplexan.
- **Varias instancias.** Con varios workers de uvicorn o varias réplicas, un
  evento solo llegaría a las conexiones del proceso que ejecutó el pipeline.
  En ese momento la capa compartida tiene que salir del proceso:

  | Pieza | Hoy (un proceso) | Con varias instancias |
  |---|---|---|
  | Reparto de eventos | `EventBroker` en memoria | **Redis pub/sub** (ya está por Celery): cada instancia se suscribe y reparte a sus conexiones locales con el mismo código de colas |
  | Buffer de replay e ids | Buffer en memoria con ids `{boot_id}-{seq}` | **Redis Stream** (`XADD` con `MAXLEN ~ 200`): ids globales, así que `Last-Event-ID` funciona contra cualquier instancia y sobra el `boot_id` |
  | Dedupe del servidor | Registro en memoria por `ticket_id` | `SET NX` por `ticket_id` con TTL |
  | Balanceador | — | Sin sticky sessions, sin buffering para `text/event-stream` y con un timeout de inactividad mayor que el keep-alive |

**2. ¿Qué estrategia de recuperación elegiste para tickets registrados mientras estabas desconectado (Last-Event-ID / replay corto, refetch-luego-SSE, o equivalente), y cómo evitas duplicados tras reconectar?**

**`Last-Event-ID` y replay corto, con refetch como respaldo** (detalle en la
§5).

- **Ids.** Cada evento lleva `id: {boot_id}-{seq}`. El cliente guarda el
  último que vio y lo envía en `Last-Event-ID` al reconectar. Eso incluye el
  `id:` del frame de apertura, para tener posición aunque no haya llegado
  ningún evento.
- **Mismo arranque, id aún en el buffer** (últimos 200 eventos): el servidor
  reenvía solo los posteriores. Es lo normal tras un corte de red.
- **Otro arranque, id fuera del buffer o mal formado:** el servidor envía
  `event: resync` con su posición actual. El cliente hace **un**
  `GET /rfp/tickets` y sigue con el mismo stream. Es el refetch-luego-SSE,
  pero solo cuando el replay no basta.

No elegimos refetch-luego-SSE en cada reconexión porque costaría una lectura
completa de la lista por cliente y por microcorte, y porque deja un hueco entre
el refetch y la apertura del stream.

**Cómo se evitan los duplicados:**

1. **En el servidor, al publicar:** un solo `rfp_ticket_created` por
   `ticket_id` en la vida del proceso. Reprocesar un ticket no vuelve a
   notificar.
2. **En el servidor, al suscribirse:** calcular el replay y registrar la cola
   ocurre bajo el mismo lock que `publish()`. Un evento llega por replay o por
   la cola, nunca por las dos vías.
3. **En el cliente:**
   - un `Set<number>` de `ticket_id` ya notificados (un aviso por ticket);
   - un upsert por `ticket_id` en la lista (una fila por ticket, aunque
     también la traiga el polling o el refetch);
   - tras un `resync`, solo se avisa de las RFP válidas que no estaban en la
     lista ni en el `Set`.

**3. ¿Por qué SSE es la herramienta correcta para notificar la llegada de un ticket y no WebSockets? ¿En qué momento dejaría de serlo — por ejemplo, si quisieras que alguien pudiera reaccionar al ticket desde el mismo canal?**

**Por qué SSE.** El flujo es de un solo sentido: el servidor avisa y el
dashboard escucha. SSE encaja exactamente:

- **Es HTTP normal.** Reutiliza `Depends(get_current_user)` con el mismo JWT,
  pasa por el proxy de Next y por el túnel de Codespaces, lo atraviesan el
  middleware de timing y el CORS existentes, y se depura con `curl -N`.
- **No añade nada.** Ni dependencias, ni protocolo nuevo, ni servidor aparte.
- **Trae lo que necesitamos.** Eventos con nombre (`event:`), ids
  (`Last-Event-ID`) y la convención de reintento (`retry:`), que es justo lo
  que usa la recuperación.

Un WebSocket obligaría a:

- montar un handshake con otro modelo de autenticación (el navegador no envía
  headers en el `upgrade`, así que el token iría en la query o en un primer
  mensaje);
- inventar un protocolo propio de ids, reintentos y heartbeat;
- mantener abierto un canal de subida que aquí nadie usa.

**Cuándo dejaría de serlo.** Cuando el mismo canal tenga que llevar mensajes
del cliente al servidor con frecuencia y baja latencia. Por ejemplo:

- que alguien «se quede» el ticket desde el aviso y los demás lo vean al
  instante con presencia («Miguel lo está mirando»);
- comentar el ticket en una conversación en vivo;
- confirmar la recepción de cada mensaje.

**El matiz.** Una reacción puntual (un clic en «Me lo quedo») todavía no
justifica cambiar de protocolo. Se resuelve con un `POST` REST normal que, al
guardarse, publica otro evento SSE para el resto del equipo. Las acciones de
la Parte 3 ya funcionan así, y el endpoint SSE ya admite otros nombres de
evento.

**El punto de corte.** Es cuando la interacción se vuelve conversacional:
muchos mensajes en ambos sentidos, presencia, «escribiendo…», confirmación por
mensaje. Ahí abrir un `POST` por mensaje y emparejarlo con el stream sale más
caro y frágil que un canal bidireccional, y WebSocket es la herramienta
correcta. Es el caso del chat de la Parte 2.
