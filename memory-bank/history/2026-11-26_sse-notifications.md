# Plan — Sistemas en Tiempo Real: Notificaciones SSE (Parte 1 de 2)

- **Rama:** `feature/sse-notifications`, creada por Marisin desde `feature/rfp-approval-completion` (PR #36 sin mergear → PR encadenado, base `feature/rfp-approval-completion`).
- **Etiqueta del PR:** `sse-notifications`.
- **Fuente de verdad:** este plan + el enunciado. El BRIEFING de la Parte 1 (`trackflow-BRIEFING.es.md` en la raíz) es **solo de apoyo**: se lee una vez en la Fase 0 y **nunca se commitea** (queda excluido en local con `.git/info/exclude`). Lo que hace falta de él está copiado abajo.
- **Sin dependencias nuevas** (FastAPI 0.141 / Starlette 1.6 y Next 16 ya bastan). Sin llamadas a LLM ni agentes en nada de lo que se añade.

---

## §0 Reglas para el agente (Claude Code del Codespace)

1. Git solo en local: prohibido `git pull`, `fetch`, `merge`, `rebase`, `push`, cambiar de rama y abrir el PR. Marisin crea la rama y hace push.
2. **Un commit por acción** (tabla de cada fase), prefijo convencional + descripción en español. Prohibido `git add .` / `-A`: rutas explícitas y `git status` antes de cada commit.
3. `trackflow-BRIEFING.es.md` es solo de lectura y de apoyo: nunca lo añadas a git, lo muevas ni lo copies al repo.
4. Prohibido leer o editar cualquier `.env*`, el JSON local de TinyDB de proveedores y `node_modules/next/dist/docs`. Si alguno aparece en `git status`, parar.
5. No instalar dependencias ni tocar `pyproject.toml`, `uv.lock`, `package.json` ni `package-lock.json`.
6. Puedes ejecutar tú `pytest` y `npm run typecheck`. **`uvicorn`, `npm run dev` y `npm run build` los ejecuta Marisin**: prepara el comando y para.
7. Tras `npm run typecheck`: `git restore uis/backoffice/tsconfig.tsbuildinfo`. Tras `npm run dev`: `git restore uis/backoffice/next-env.d.ts`. Nunca commitearlos.
8. Una fase cada vez. Al terminar: resumen con la plantilla del final y 🛑 **STOP** hasta recibir `OK fase N, continúa`.
9. No rediseñes el sistema de RFPs: solo se le añade la notificación. No cambies nombres de campos ni valores de estado existentes.

---

## BRIEFING de la Parte 1 — lo esencial (copiado para no depender del fichero)

- Quién lo ve: el equipo comercial de **Miguel Torres** (Commercial Director), que hoy se entera de una RFP nueva revisando el dashboard.
- Entidades a reutilizar sin renombrar: **Ticket** (`ticket_id`, `rfp_id`, `status`) y **RFP metadata** (`client_name`, `client_country`, `services_requested`, `monthly_volume`, `deadline`, `budget_range`, `departments_needed`).
- Disparo: cuando un ticket nuevo entra con el estado inicial de análisis, es decir, cuando el documento se clasificó como RFP válida y el flujo empieza a procesarlo.
- Wire sugerido: `event: rfp_ticket_created` + `data:` con un JSON plano de campos del ticket (sin sobre `{"event","data"}`): `ticket_id`, `rfp_id`, `client_name`, `client_country`, `services_requested`, `status`, `created_at`. Sin el documento completo ni las secciones por departamento.
- Opcionales con datos reales (no se hacen, D14): `sla_threshold_alert` (SLA de entrega < 90 % en cualquier país → Thomas, CEO, y Ana, Warehouse Operations) y `ticket_escalated_to_senior` (`ticket_id` + motivo).
- Restricciones: nombres de campos idénticos a los del sistema de RFPs; la Parte 2 (chat WebSocket) tendrá su propio BRIEFING y no debe copiar el esquema `Ticket`.

## Rúbrica resumida (lo que se evalúa)

- El dashboard (página **RFPs** del backoffice) muestra un ticket nuevo **sin recargar**.
- Cortar y restablecer la red → reconexión con **backoff progresivo** + **estrategia de recuperación documentada**, **sin duplicar** el mismo `ticket_id`.
- El stream exige **el mismo JWT** del backoffice; el cliente lo envía con **`fetch` + `ReadableStream`** (no `EventSource`).
- Evento **nombrado** `rfp_ticket_created` con **payload estructurado**; tests sobre `text/event-stream`, `event:` y forma del JSON en `data:`.
- Ninguna llamada a modelo o agente en esta parte.
- Nombres de campos y entidades = los del sistema de RFPs.
- PR con las respuestas a las 3 preguntas de diseño.

---

## Decisiones ya tomadas (no improvisar)

| # | Decisión | Justificación |
|---|----------|---------------|
| D1 | **Estado `analizando`**, no `analyzing`. Todos los nombres y valores salen de lo que ya existe (`data/pipelines/rfp_intake/config.py`: `STATUS_ANALYZING = "analizando"`; `ticket_id` entero; `client_country` = `"United States"` / `"Spain"`). | El BRIEFING §5 exige que «los nombres de campos coincidan exactamente con los que ya usaste en el sistema de RFPs». El ejemplo del BRIEFING (`"analyzing"`, `"tkt_0225"`, `"US"`) es ilustrativo; nuestro sistema persiste otros valores. Se documenta en el diseño y en el PR. |
| D2 | **Momento de emisión:** en `runner.process_ticket`, justo después de `store.save_metadata(...)` del nodo `extract_metadata`. El ticket ya está clasificado como RFP válida, el estado sigue en `analizando` y ya hay `client_name`, `client_country` y `services_requested`. Un documento descartado **nunca** emite. | BRIEFING §2: «cuando el documento fue clasificado como una RFP válida y el flujo empieza a procesarlo». Emitir en el `POST` daría metadatos vacíos y notificaría PDFs que luego se descartan. |
| D3 | **Desacople pipeline ↔ web:** `data/pipelines/rfp_intake/events.py` con `subscribe(listener)` / `emit(event, payload)` (lista de listeners, nunca lanza: un listener que falla se registra en log y no rompe el pipeline). `services/realtime/` registra el broker como listener al importarse. | El pipeline no debe importar FastAPI ni `services.*` (en Docker el paquete es `api`, no `services.api`). |
| D4 | **Broker en memoria** `services/realtime/broker.py` (`EventBroker`): una `asyncio.Queue(maxsize=100)` por suscriptor; `publish()` es **thread-safe** (`loop.call_soon_threadsafe`, porque el pipeline corre en el threadpool de `BackgroundTasks`); **buffer circular** de los últimos 200 eventos; ids `"{boot_id}-{seq}"` (`boot_id` = epoch de arranque) para detectar reinicios; un suscriptor con la cola llena se desconecta (el cliente se reconecta y recupera). **Dedupe en servidor:** un solo `rfp_ticket_created` por `ticket_id` por proceso (reprocesar con `--ticket-id` no vuelve a notificar). | Suficiente para un único proceso uvicorn; la respuesta de escalado (Redis pub/sub, que ya tenemos por Celery) va en las preguntas de diseño. |
| D5 | **Endpoint** `GET /realtime/events` en `services/realtime/router.py`, `Depends(get_current_user)` (mismo JWT; sin token → 401 antes de abrir el stream). `response_class=StreamingResponse`, `response_model=None`, `include_in_schema=True`. | Endpoint genérico para que el caso opcional pueda reutilizarlo con otro nombre de evento. |
| D6 | **Headers:** `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-cache, no-transform`, `Connection: keep-alive`, `X-Accel-Buffering: no`. Al abrir: `retry: 3000` + comentario `: connected`. **Keep-alive:** comentario `: keep-alive` cada `SSE_KEEPALIVE_SECONDS` (por defecto 15) cuando no hay eventos. | `no-transform` evita que la compresión del dev server de Next (proxy `/api/backend`) acumule el stream; el primer comentario hace que los headers salgan ya. |
| D7 | **Wire del evento** (sin sobre anidado, una sola línea `data:`): `id: <boot>-<seq>` / `event: rfp_ticket_created` / `data: {json}`. Campos del `data`: los 7 del BRIEFING — `ticket_id`, `rfp_id`, `client_name`, `client_country`, `services_requested`, `status`, `created_at` — más `stage` y `original_filename` (nombres que ya existen en `RfpTicketSummary`) para pintar la fila sin pedir el ticket. Esquema Pydantic `RfpTicketCreatedEvent` en `services/realtime/schemas.py`. | Lo justo para saber qué llegó y que requiere procesamiento (BRIEFING §3). |
| D8 | **Recuperación = `Last-Event-ID` + replay corto, con `resync` de respaldo.** El cliente envía `Last-Event-ID` (header) al reconectar; el servidor reenvía los eventos posteriores del buffer. Si el id es de otro arranque o ya salió del buffer, el servidor envía `event: resync` (`data: {"reason": "..."}`) y el cliente hace **un** `GET /rfp/tickets` y sigue con el stream. | Opción aceptada por el enunciado; el `resync` cubre reinicios de la API sin perder tickets en silencio. |
| D9 | **Dedupe en cliente:** `Set<number>` de `ticket_id` ya notificados + `upsert` por `ticket_id` en la lista (nunca dos filas ni dos avisos para el mismo ticket). Los ids recuperados en un `resync` que ya estaban en la lista no generan aviso. | Rúbrica: sin duplicar UI tras reconectar. |
| D10 | **Cliente** `uis/backoffice/src/lib/sse.ts`: `connectSse({ path, onEvent, onStatus, signal })` con `fetch` (`Authorization: Bearer`, `Accept: text/event-stream`, `Last-Event-ID`, `cache: "no-store"`), `response.body.getReader()` + `TextDecoder` y parser de frames (`event`, `data` multilínea, `id`, `retry`, comentarios, `\r\n`). **Backoff:** 1 s, 2 s, 4 s, 8 s, 16 s, máx. 30 s, con jitter ±20 %, reinicio tras abrir bien. **401** → no reintenta, estado `unauthorized`. Abortable con `AbortController` al desmontar. Hook `useRfpNotifications` en `uis/backoffice/src/lib/rfp-notifications.ts`. | `EventSource` no permite `Authorization` (enunciado). |
| D11 | **UI** (`uis/backoffice/src/app/rfp/page.tsx`): indicador de conexión («En directo» / «Reconectando en N s…» / «Sesión caducada»); aviso **visualmente distinto** (banda/toast verde esmeralda con badge «Nueva RFP», cliente, país, servicios, `#ticket_id`, «requiere procesamiento»), descartable, y la fila nueva resaltada con badge «Nuevo». El evento hace `upsert` local de la fila: **no** se vuelve a pedir la lista por cada evento. El polling actual se mantiene **solo** para el progreso de tickets ya en marcha (no para descubrir tickets nuevos); se documenta. | Rúbrica: notificación distinguible, sin recarga ni refetch por evento. |
| D12 | **Contrato de rutas 51 → 52.** `tests/test_serialization_contracts.py`: el stream es la única ruta sin `response_model` que no es 204 → nuevo conjunto `DOCUMENTED_STREAM_ENDPOINTS` con su nombre. | La trampa conocida del monorepo. |
| D13 | **Tests sin colgarse:** el router lee `get_stream_settings()` (dependencia sobreescribible) con `keepalive_seconds` y `close_after_replay` (solo tests: cierra el stream tras replay + eventos pendientes). Los tests publican antes de conectar y leen la respuesta completa con `TestClient`. | Un stream infinito bloquea `TestClient`. |
| D14 | **Caso opcional: no se implementa** en esta entrega (prioridad: plazo). Se menciona en el PR que el endpoint ya admite otros nombres de evento (`sla_threshold_alert`, `ticket_escalated_to_senior`). | Opcional según el enunciado. |

## Hallazgos del código (confírmalos en la Fase 0)

- `services/rfp/router.py`: `POST /rfp/tickets` crea el ticket en `analizando` y encadena en `BackgroundTasks` `runner.process_ticket_safely` → drafting → approval. Las funciones son síncronas → corren en el threadpool.
- `data/pipelines/rfp_intake/runner.py` (`process_ticket`): `extract_metadata` → `store.save_metadata(...)` → `stage = STAGE_ORCHESTRATING`. Ahí va la emisión (D2).
- `services/api/security.py`: `get_current_user` con `OAuth2PasswordBearer` (header `Authorization: Bearer`).
- `services/api/main.py`: `app.include_router(rfp_router)` al final de la lista; hay `timing_middleware` (`@app.middleware("http")`): comprueba que no rompe el streaming (Starlette 1.6 lo soporta).
- `uis/backoffice/src/lib/api.ts`: `getAuthToken()` y `API_URL = "/api/backend"` (proxy de `next.config.ts`; en Codespaces el navegador no llega a `:8000`).
- `uis/backoffice/src/app/rfp/page.tsx`: `refresh()` con `listRfpTickets()` y `setInterval(POLL_INTERVAL_MS)` solo mientras hay trabajo; un ticket que sube otra persona no aparece hasta recargar.
- `tests/test_rfp_routes.py`: fixture con `InMemoryRfpStore` y `dependency_overrides[get_current_user]` — reutiliza el patrón.
- `tests/test_serialization_contracts.py`: `assert len(routes) == 51`.

## Ficheros autorizados

- Nuevos: `data/pipelines/rfp_intake/events.py`, `services/realtime/__init__.py`, `broker.py`, `schemas.py`, `router.py`, `uis/backoffice/src/lib/sse.ts`, `uis/backoffice/src/lib/rfp-notifications.ts`, `tests/test_realtime_sse.py`, `tests/pipelines/test_rfp_ticket_created_event.py`, `docs/realtime-sse/sse-design.md`, `docs/realtime-sse/manual-verification.md`, `docs/realtime-sse/evidence/` (capturas), `memory-bank/history/2026-11-26_sse-notifications.md`, `prompts/sse-notifications/prompt.md`.
- Modificados: `data/pipelines/rfp_intake/runner.py`, `services/api/main.py`, `tests/test_serialization_contracts.py`, `uis/backoffice/src/lib/rfp.ts` (solo tipos/helper si hace falta), `uis/backoffice/src/app/rfp/page.tsx`, `memory-bank/progress.md`, `prompts/README.md`.
- Cualquier otro fichero: pregunta antes.

---

## Fase 0 — Reconocimiento y línea base

| # | Acción | Commit |
|---|--------|--------|
| 0.1 | `git branch --show-current` = `feature/sse-notifications`; `git log -1` = último commit de la Parte 3 de RFPs. Si no, STOP. | — |
| 0.2 | Leer `AGENTS.md`, `uis/backoffice/AGENTS.md`, `memory-bank/progress.md` (primera entrada) y confirmar los hallazgos de arriba (cita fichero:línea). | — |
| 0.3 | `pytest -q tests/test_rfp_routes.py tests/test_serialization_contracts.py` → línea base en verde. | — |
| 0.4 | Mover el plan y el prompt subidos por Marisin a su sitio (si no están ya) y añadir la fila `sse-notifications` a `prompts/README.md`. | `docs: añade el plan y el prompt de las notificaciones SSE` |
| 0.5 | Leer `trackflow-BRIEFING.es.md` (raíz) y comprobar que coincide con «BRIEFING de la Parte 1 — lo esencial». **No** moverlo, **no** commitearlo y **no** citarlo por ruta en docs ni código. Si aparece en `git status`, debe ser porque falta la línea en `.git/info/exclude`: para y avisa. | — |

✅ Aceptación: rama correcta, hallazgos confirmados, línea base verde, BRIEFING leído y fuera de git. 🛑 STOP.

## Fase 1 — Backend SSE (`services/`)

| # | Acción | Commit |
|---|--------|--------|
| 1.1 | `data/pipelines/rfp_intake/events.py` (D3) con `EVENT_RFP_TICKET_CREATED = "rfp_ticket_created"`. | `feat: añade el gancho de eventos del pipeline de RFPs` |
| 1.2 | Emitir en `runner.process_ticket` tras `save_metadata` (D2, D7): payload con los campos del ticket y de los metadatos guardados (`store.get_ticket(ticket_id)`), `created_at` en ISO 8601 UTC. | `feat: emite rfp_ticket_created cuando la RFP es válida` |
| 1.3 | `services/realtime/schemas.py` + `broker.py` (D4, D7, D8): `publish`, `subscribe(last_event_id)` → (replay \| resync, cola), `format_sse(...)`, dedupe por `ticket_id`. | `feat: añade el broker de eventos en tiempo real` |
| 1.4 | `services/realtime/router.py` (D5, D6, D13) y registro del listener del pipeline; `include_router` en `services/api/main.py` (con el mismo `try/except` de import que `services/rfp/router.py` para Docker). Al arrancar la app el broker guarda el event loop (`startup`). | `feat: añade el endpoint SSE /realtime/events protegido con JWT` |
| 1.5 | Contrato de rutas 51 → 52 (D12). | `test: actualiza el contrato de rutas con el stream SSE` |

✅ Aceptación: `pytest -q tests/test_serialization_contracts.py tests/test_rfp_routes.py tests/pipelines/` verde. Comandos para Marisin: arrancar la API y `curl -N` con su token (ver plantilla). 🛑 STOP.

## Fase 2 — Tests del endpoint (`tests/`)

| # | Acción | Commit |
|---|--------|--------|
| 2.1 | `tests/test_realtime_sse.py`: (a) sin token → 401 y sin stream; (b) con JWT → 200, `content-type` empieza por `text/event-stream`, `cache-control` con `no-cache`; (c) el wire contiene `retry:`, `id:`, `event: rfp_ticket_created` y una línea `data:` cuyo JSON tiene **exactamente** los campos de D7, `status == "analizando"`, `ticket_id` entero y **sin** sobre `{"event","data"}`; (d) `Last-Event-ID` del mismo arranque → solo los eventos posteriores; (e) id de otro arranque o fuera del buffer → `event: resync`; (f) mismo `ticket_id` publicado dos veces → un solo frame; (g) keep-alive: con `keepalive_seconds` pequeño y sin eventos aparece `: keep-alive`. | `test: prueba el endpoint SSE de tickets de RFP` |
| 2.2 | `tests/pipelines/test_rfp_ticket_created_event.py`: con el grafo/LLM falsos de los tests existentes del pipeline, una RFP válida emite **un** `rfp_ticket_created` con `client_name` ya relleno y un documento descartado **no** emite; un listener que lanza no rompe el pipeline. | `test: prueba la emisión del evento desde el pipeline` |

✅ Aceptación: suite completa `pytest -q` verde (indica el total). 🛑 STOP.

## Fase 3 — Frontend (`uis/backoffice`)

| # | Acción | Commit |
|---|--------|--------|
| 3.1 | `src/lib/sse.ts` (D10): parser de frames + `connectSse` con backoff, `Last-Event-ID`, 401 y abort. Log en consola `[sse]` de cada (re)conexión y del retardo del backoff (sirve de evidencia). | `feat: añade el cliente SSE con fetch y backoff` |
| 3.2 | `src/lib/rfp-notifications.ts`: tipo `RfpTicketCreatedEvent` y hook `useRfpNotifications({ onTicket, onResync })` con el `Set` de dedupe (D9). | `feat: añade el hook de notificaciones de RFP` |
| 3.3 | `src/app/rfp/page.tsx` (D11): indicador de conexión, aviso «Nueva RFP», `upsert` de la fila, resaltado «Nuevo», `resync` → un `listRfpTickets()`. Sin `EventSource`. | `feat: muestra en directo los tickets de RFP nuevos` |
| 3.4 | `npm run typecheck` (y `git restore uis/backoffice/tsconfig.tsbuildinfo`). | — |

✅ Aceptación: typecheck limpio; `grep -rn "EventSource" uis/backoffice/src` vacío. Comandos para Marisin: `npm run dev` y prueba en navegador. 🛑 STOP.

## Fase 4 — Documentación y verificación manual

| # | Acción | Commit |
|---|--------|--------|
| 4.1 | `docs/realtime-sse/sse-design.md`: arquitectura (diagrama de texto pipeline → events → broker → `/realtime/events` → proxy Next → `fetch`), wire de ejemplo real, D1 (por qué `analizando`), headers y keep-alive, estrategia de recuperación + dedupe, límites (un proceso) y **respuestas a las 3 preguntas de diseño**. | `docs: documenta el diseño de las notificaciones SSE` |
| 4.2 | `docs/realtime-sse/manual-verification.md`: guion de la prueba de caída (ver abajo) con huecos para los resultados y las capturas. | `docs: añade el guion de verificación manual de reconexión` |
| 4.3 | Entrada nueva **arriba** de `memory-bank/progress.md`. | `docs: registra las notificaciones SSE en el progreso` |

**Guion de verificación manual (lo ejecuta Marisin):**
1. API + backoffice arrancados; página RFPs con «En directo». Pestaña B (o `curl -N`) abierta a la vez.
2. Subir una RFP válida → aparece sola en ambas pestañas, aviso «Nueva RFP», sin recargar.
3. DevTools → Network → **Offline** en la pestaña A; la consola muestra `[sse]` con retardos crecientes (1 s, 2 s, 4 s…).
4. Mientras está offline, subir otra RFP desde la pestaña B.
5. Volver a **Online** → la pestaña A reconecta con `Last-Event-ID`, recibe el ticket perdido por replay y lo muestra **una sola vez**.
6. Reiniciar la API con la pestaña A abierta → reconecta, llega `resync`, refetch único, sin duplicados.
7. Subir un PDF que no es RFP → no hay aviso.

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

- [ ] `GET /realtime/events` con JWT del backoffice; 401 sin token
- [ ] `text/event-stream`, `no-cache, no-transform`, keep-alive por comentarios
- [ ] `event: rfp_ticket_created` + `data:` JSON con los campos del sistema de RFPs y `status = analizando`
- [ ] Emisión al clasificarse como RFP válida; descartados no emiten
- [ ] Cliente `fetch` + `ReadableStream` con `Authorization: Bearer`; sin `EventSource`
- [ ] Backoff progresivo con tope; 401 no reintenta
- [ ] `Last-Event-ID` + replay; `resync` → refetch único; dedupe por `ticket_id`
- [ ] Aviso visualmente distinto; sin recarga ni refetch por evento
- [ ] Tests de headers, nombre de evento y forma del JSON; contrato 52 rutas
- [ ] Verificación manual documentada con capturas
- [ ] Ninguna llamada a modelo/agente en el código nuevo
- [ ] PR con las 3 preguntas de diseño respondidas
- [ ] `trackflow-BRIEFING.es.md` no está en ningún commit (`git log --all -- trackflow-BRIEFING.es.md` vacío)
