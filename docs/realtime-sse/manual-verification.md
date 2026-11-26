# Verificación manual — notificaciones SSE y reconexión

Guion de la prueba en navegador de `GET /realtime/events` y de la página
**RFPs** del backoffice. Lo ejecuta Marisin. El diseño está en
[`sse-design.md`](sse-design.md) y las capturas en [`evidence/`](evidence/).

**Entorno:** Codespaces, rama `feature/sse-notifications`, 2026-11-26.

**Preparación:**

```bash
# Terminal 1 — API (raíz del repo)
python -m uvicorn services.api.main:app --reload --port 8000
# Terminal 2 — backoffice
cd uis/backoffice && npm run dev      # al terminar: git restore uis/backoffice/next-env.d.ts
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

**Pasos:** en la pestaña A, DevTools → Network → **Offline**. Esperar unos 30 s.

| Esperado | Resultado | Evidencia |
|---|---|---|
| El indicador pasa a «Reconectando en N s… (intento k)» | ⏳ | — |
| La consola muestra `[sse] reconectando en …` con retardos crecientes: ~1 s, 2 s, 4 s, 8 s, 16 s, con un máximo de 30 s y ±20 % de jitter | ⏳ _(anotar los retardos)_ | — |

## 4. Llega una RFP mientras la pestaña A está offline

**Pasos:** con la pestaña A todavía en Offline, subir otra RFP válida desde la
pestaña B.

| Esperado | Resultado | Evidencia |
|---|---|---|
| La pestaña B la muestra; la pestaña A, no | ⏳ | — |

## 5. Vuelta a Online: replay sin duplicados

**Pasos:** en la pestaña A, cambiar Network a **No throttling**.

| Esperado | Resultado | Evidencia |
|---|---|---|
| La consola muestra `[sse] conectando … (Last-Event-ID: <boot>-<n>)` y luego `[sse] conectado tras k reintento(s)` | ⏳ | — |
| Llega por replay el ticket perdido y aparece **una sola vez**, con aviso y etiqueta «Nuevo» | ⏳ | — |
| En la petición `events` nueva, Request headers incluyen `Last-Event-ID` | ⏳ | — |

## 6. Reinicio de la API: `resync`

**Pasos:** con la pestaña A abierta, reiniciar uvicorn (Ctrl+C y volver a
lanzarlo, o guardar un `.py` con `--reload`).

| Esperado | Resultado | Evidencia |
|---|---|---|
| La pestaña A reconecta y la consola muestra `[sse] resync: server_restarted` | ⏳ | — |
| Se hace un único `GET /rfp/tickets` (Network) y no se duplica ninguna fila ni ningún aviso | ⏳ | — |

## 7. Un PDF que no es RFP no avisa

**Pasos:** subir `trackflow-request-3.pdf` (el pitch de RapidShip).

| Esperado | Resultado | Evidencia |
|---|---|---|
| El ticket queda **Descartado** y no aparece ningún aviso «Nueva RFP» | ✅ el #4 `trackflow-request-3.pdf` está «Descartado» (18:00:05) sin aviso; el único aviso es el del #5 válido (18:00:58) | `evidence/sse-ui-nueva-rfp.png` |

## Conclusión

Pendiente de completar cuando se ejecuten los pasos 3 a 6 y se haga la captura
de la pestaña B del paso 2.
