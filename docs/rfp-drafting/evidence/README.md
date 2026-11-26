# Evidencias — Flujo agéntico de RFPs, Parte 2 (generación y evaluación de respuestas)

Ejecutadas en el Codespace el 26/11/2026 sobre la rama `feature/rfp-response-generation`, con Supabase y el LLM de
4Geeks. Las capturas de la UI marcadas como «compuestas» son dos recortes de la **misma** captura de página entera,
puestos uno debajo del otro (separados por una línea gris) para que se vea a la vez de qué ticket son y cómo
terminó cada sección; no se ha editado nada. El texto completo de cada borrador está en los JSON.

## Base de datos y tests

| Evidencia | Qué demuestra |
|---|---|
| `rfp-drafting-supabase-columns.png` | `services/sql/004_rfp_drafting.sql` aplicado en Supabase: `rfp_department_sections` 20, `rfp_metadata` 18 y `rfp_tickets` 20 columnas. |
| `rfp-drafting-tests-pipelines.png` | `pytest tests/pipelines -k rfp_drafting -q` → **50 passed**: generadores, evaluadores (incluido el fallo de compliance del BRIEFING §5 «devoluciones en menos de 48 h»), ciclo generador-evaluador, runner y almacén SQL. |
| `rfp-drafting-tests-routes.png` | `pytest tests/test_rfp_routes.py tests/test_serialization_contracts.py -q` → **25 passed**: `POST /rfp/tickets/{id}/drafts` (202/404/409), recorrido completo POST → Parte 1 → Parte 2 y contrato de 47 rutas. |

La suite completa da **758 passed, 1 skipped** antes de la corrección de pertinencia (`fix:` de esta rama), que añade un test más.

## Demostración del ciclo, sin BD (`scripts/rfp_drafting_run.py --demo`)

| Evidencia | Qué demuestra |
|---|---|
| `rfp-drafting-demo-retry.png` · `demo-retry.json` | ModaViva (EUR). La 1.ª versión de `reverse` se sabotea a propósito: promete devoluciones en 24 horas, no trae tabla de descuentos y da una tarifa negociada de UPS → falla `returns-min-48h`, `volume-discount-table`, `no-carrier-negotiated-rates` y `no-invented-figures`. Vuelve al generador con el feedback; el LLM corrige las cuatro reglas en la iteración 2 pero olvida una pregunta abierta (pertinencia) y en la 3 pasa. `warehouse` pasa a la primera. Resultado: `drafts_ready`. |
| `rfp-drafting-demo-review.png` · `demo-review.json` | Luna (USD). `warehouse` incumple las mismas reglas en las 3 iteraciones → agota el límite y queda en **`needs_human_review`** con su último borrador y su `EvaluationResult`, incluida en el handoff a la Parte 3. `lastmile` (LLM real) pasa en la iteración 2 sin quedar bloqueada. |

## UI del backoffice con los tickets reales (`/rfp`)

| Evidencia | Qué demuestra |
|---|---|
| `rfp-drafting-ui-en-evaluacion.png` | Momento de una ejecución de ModaViva (11:29): `warehouse` «Evaluando» en la iteración 1 con la pertinencia en rojo («Sin responder: nombre del cliente «ModaViva»»), mientras `reverse` ya superó la evaluación. En esa ejecución `warehouse` pasó en la iteración 2. |
| `rfp-drafting-ui-modaviva.png` (compuesta) · `ticket-1-modaviva-drafts.json` | Ticket #1 tras regenerar (11:38): «En evaluación» / «Borradores listos», handoff `trackflow.rfp_drafting.handoff/v1`, 2 secciones a la primera, en EUR. |
| `rfp-drafting-ui-luna.png` (compuesta) · `ticket-2-luna-drafts.json` | Ticket #2 (11:42): «En evaluación» / «Borradores listos», media de 1,5 iteraciones; `warehouse` a la primera y `lastmile` en la iteración 2 (falló, recibió feedback y se corrigió). En USD, con el tramo del 5 % para 5.000 pedidos y el SLA del 90 %. |

## Observaciones

- En la primera regeneración de ModaViva la UI mostró un «Error 502» sin detalle mientras consultaba el estado; el
  ticket terminó bien. Es el proxy del Codespace cortando una consulta del polling, no un fallo del pipeline.
- Las capturas de página entera pueden duplicar trozos al hacer scroll; por eso se usan recortes y los JSON.
