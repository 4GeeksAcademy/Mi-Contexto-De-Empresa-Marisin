# Verificación manual — notificaciones SSE y reconexión

Guion de la prueba en navegador de `GET /realtime/events` y de la página
**RFPs** del backoffice. Lo ejecuta Marisin. El diseño está en
[`sse-design.md`](sse-design.md) y las capturas en [`evidence/`](evidence/).

**Entorno:** Codespaces, rama `feature/sse-notifications`, 2026-11-26.

**Preparación:**

```bash
# Terminal 1 — API (raíz del repo). Sin --timeout-graceful-shutdown, Ctrl+C no
# cierra uvicorn mientras haya streams SSE abiertos (ver Observaciones).
python -m uvicorn services.api.main:app --port 8000 --timeout-graceful-shutdown 3
# Terminal 2 — backoffice
cd uis/backoffice && npm run dev      # al terminar: git restore uis/backoffice/next-env.d.ts
# Pasos 3-6 (replay sin recargas de HMR): build de producción
cd uis/backoffice && npm run build && npm run start
```

**Token para `curl`:**

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"<usuario>","password":"<contraseña>"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
```

**Leyenda:** ✅ comprobado con captura · ⏳ pendiente.

## 0. El stream con `curl`

| Prueba | Esperado | Resultado | Evidencia |
|---|---|---|---|
| `curl -i -N localhost:8000/realtime/events` | `401 Unauthorized`, `www-authenticate: Bearer`, cuerpo JSON (no es un stream) | ✅ 401 con `{"detail":"Not authenticated"}` | `evidence/sse-curl-401.png` |
| `curl -i -N -H "Authorization: Bearer $TOKEN" …/realtime/events` | `200` con los headers de la tabla de abajo; después `retry: 3000`, `id: <boot>-0`, `: connected` y `: keep-alive` cada 15 s | ✅ 200; `id: 1795708225-0`; keep-alives cada 15 s | `evidence/sse-curl-stream.png` |

Headers esperados en la respuesta 200:

| Header | Valor |
|---|---|
| `Content-Type` | `text/event-stream; charset=utf-8` |
| `Cache-Control` | `no-cache, no-transform` |
| `Connection` | `keep-alive` |
| `X-Accel-Buffering` | `no` |

## 1. Página RFPs «En directo» (pestaña A y pestaña B o `curl -N`)

| Esperado | Resultado | Evidencia |
|---|---|---|
| El indicador junto a «Tickets» dice **En directo**. En la consola aparecen `[sse] conectando a /realtime/events (conexión nueva)` y `[sse] conectado` (en desarrollo, el «conectando» sale dos veces por el doble montaje de React) | ✅ | `evidence/sse-ui-en-directo.png` |
| En Network, la petición `events` va a `/api/backend/realtime/events` y responde `200` con `text/event-stream; charset=utf-8` y `no-cache, no-transform` | ✅ a través del proxy de Next y del túnel de Codespaces | `evidence/sse-ui-network-fetch.png` |

Observación sobre la captura de Network: en unos 16 minutos de sesión aparecen
varias peticiones `events`, algunas canceladas. Cada recarga, cada recarga
en caliente de Next y cada reinicio de `--reload` abren una conexión nueva. Si
se repitieran sin ninguna de esas causas, anotar aquí cada cuánto ocurre.

## 2. Una RFP válida aparece sola

**Pasos:** subir una RFP válida (por ejemplo `trackflow-request-1.pdf`,
ModaViva) y no recargar.

| Esperado | Resultado | Evidencia |
|---|---|---|
| Aviso esmeralda **Nueva RFP** con `#ticket_id`, cliente, país, servicios, `rfp_id` y «requiere procesamiento» | ✅ «#5 · ModaViva — España · Almacenamiento, Devoluciones» | `evidence/sse-ui-nueva-rfp.png` |
| La fila aparece en la lista con el anillo y la etiqueta **Nuevo**, sin recargar la página | ✅ | `evidence/sse-ui-nueva-rfp.png` |
| La pestaña B (o el `curl -N`) recibe a la vez `event: rfp_ticket_created` | ⏳ _(no hay captura)_ | — |

## 3. Corte de red: backoff progresivo

**Pasos:** en la pestaña A, DevTools → Network → **Offline**. Esperar unos 60 s.

| Esperado | Resultado | Evidencia |
|---|---|---|
| El indicador pasa a «Reconectando en N s… (intento k)» | ✅ «Reconectando en 36 s… (intento 6)» | `evidence/sse-reconexion-backoff.png` |
| La consola muestra `[sse] reconectando en …` con retardos crecientes: ~1 s, 2 s, 4 s, 8 s, 16 s, con un máximo de 30 s y ±20 % de jitter | ✅ **1,0 → 2,3 → 3,6 → 7,5 → 16,9 → 36,0 s**. Cada intento sale con `Failed to fetch` y reenvía `Last-Event-ID: 1795708225-1`. Los 36,0 s son el tope de 30 s con +20 % de jitter | `evidence/sse-reconexion-backoff.png` |

La primera línea, «conexión perdida: signal is aborted without reason», es el
corte inmediato que provoca el evento `offline` del navegador.

## 4. Llega una RFP mientras la pestaña A está offline

**Pasos:** con la pestaña A todavía en Offline, subir otra RFP válida desde la
pestaña B.

| Esperado | Resultado | Evidencia |
|---|---|---|
| La pestaña A no la muestra mientras está offline | ✅ Se subió el #7 (ModaViva, 18:47:02) con la pestaña A offline; A siguió reintentando con `Last-Event-ID: 1795708225-2` | `evidence/sse-reconexion-replay.png` |

## 5. Vuelta a Online: replay sin duplicados

**Pasos:** en la pestaña A, cambiar Network a **No throttling**. Esta prueba se
hizo con `npm run build` y `npm run start` (ver la observación a).

| Esperado | Resultado | Evidencia |
|---|---|---|
| La consola muestra `[sse] conectando … (Last-Event-ID: <boot>-<n>)` y luego `[sse] conectado tras k reintento(s)` | ✅ `Last-Event-ID: 1795708225-2` y «conectado tras 8 reintento(s)». Retardos: 1,0 → 1,7 → 4,1 → 8,3 → 13,0 → 32,3 → 32,7 → 24,5 s | `evidence/sse-reconexion-replay.png` |
| El ticket perdido llega por replay y aparece **una sola vez**, con aviso y etiqueta «Nuevo», sin recargar | ✅ Aviso «Nueva RFP · #7 · ModaViva — España · Almacenamiento, Devoluciones» y una sola fila #7 con «Nuevo» | `evidence/sse-reconexion-replay.png` |

En la captura sigue visible el «Failed to fetch» que dejó el polling durante el
corte, aunque la conexión ya se recuperó. Es el fallo que corrige el commit
`fix: refresh() borra el error de carga cuando la lista vuelve a cargar bien`.

## 6. Reinicio de la API: `resync`

**Pasos:** con la pestaña A abierta, parar uvicorn (Ctrl+C) y volver a
arrancarlo con `--timeout-graceful-shutdown 3`.

| Esperado | Resultado | Evidencia |
|---|---|---|
| Mientras la API está caída, la pestaña A reintenta con backoff | ✅ «network error» y después `HTTP 500` (lo responde el proxy de Next sin la API detrás). Retardos: 0,9 → 2,2 → 3,9 → 7,8 → 14,7 → 32,3 → 29,1 → 34,5 → 32,7 s, siempre con `Last-Event-ID: 1795708225-3` | `evidence/sse-resync-reinicio.png` |
| Al volver la API, reconecta y la consola muestra `[sse] resync: server_restarted` | ✅ «conectado tras 9 reintento(s)» seguido de `[sse] resync: server_restarted` | `evidence/sse-resync-reinicio.png` |
| Un único `GET /rfp/tickets` y ninguna fila ni aviso duplicados | ✅ El log de la API muestra, tras el arranque, un `GET /realtime/events` y un `GET /rfp/tickets` por pestaña. La lista mantiene una sola fila por ticket y un solo aviso del #7 | `evidence/sse-resync-api-log.png`, `evidence/sse-resync-reinicio.png` |

El banner «Error 500:» de la captura es el mismo fallo del paso 5, ya
corregido.

## 7. Un PDF que no es RFP no avisa

**Pasos:** subir `trackflow-request-3.pdf` (el pitch de RapidShip).

| Esperado | Resultado | Evidencia |
|---|---|---|
| El ticket queda **Descartado** y no aparece ningún aviso «Nueva RFP» | ✅ El #4 `trackflow-request-3.pdf` quedó «Descartado» (18:00:05) sin aviso; el único aviso es el del #5 válido (18:00:58) | `evidence/sse-ui-nueva-rfp.png` |

## Observaciones

- **a) HMR en `npm run dev`.** Al volver la red, el dev server de Next recarga
  la página entera: la conexión empieza de cero, sin `Last-Event-ID`, y la
  prueba de replay no sería válida. Por eso los pasos 3 a 6 se hicieron con
  `npm run build` y `npm run start`.
- **b) Cierre de uvicorn.** Con streams SSE abiertos, Ctrl+C se queda
  esperando a que terminen las conexiones (en el log se ve `^CKilled`). Hay
  que arrancarlo con `--timeout-graceful-shutdown 3`. Está documentado en la
  §8 de `sse-design.md`.
- **c) Polling durante la caída.** Mientras dura el corte, el polling de los
  tickets en marcha también falla y muestra su error. Desde el fix, ese error
  desaparece en la siguiente carga correcta.

## Conclusión

La rúbrica queda verificada en navegador:

- **Ticket nuevo sin recargar** (pasos 1 y 2).
- **Reconexión con backoff progresivo y con tope** (pasos 3 y 6).
- **Recuperación sin duplicados:** por `Last-Event-ID` con replay (paso 5) y
  por `resync` con un único refetch tras reiniciar la API (paso 6).
- **Un documento descartado no notifica** (paso 7).

Queda sin captura la recepción simultánea en la pestaña B del paso 2.
