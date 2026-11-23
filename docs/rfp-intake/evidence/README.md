# Evidencias — Flujo agéntico de RFPs · Parte 1

Capturas y exportaciones de la verificación en el Codespace (plan: `memory-bank/history/2026-11-22_rfp-intake.md` §4).

| Fichero | Qué muestra |
|---|---|
| `rfp-tests-pipelines.png` | 68 tests del clasificador, workers, metadatos, orquestador, synthesizer, grafo (LangGraph real) y almacén SQL (SQLite real) |
| `rfp-tests-routes.png` | 21 tests de los endpoints (202, PDF en `data/raw/rfp/`, 415/422, 401, 404, 503, recorrido completo) y del contrato de rutas (46) |
| `rfp-supabase-tables.png` | Las tres tablas en Supabase: `rfp_department_sections` 16, `rfp_metadata` 18 y `rfp_tickets` 18 columnas |
| `rfp-api-routes.png` | Swagger del backend existente (`:8000/docs`): la sección `rfp` junto a `tasks`, `knowledge` y `agent`, sin API nuevo |
| `rfp-ui-analizando.png` | Asíncrono: Luna Cosmetics en «Analizando por departamento… (se actualiza solo)» con los metadatos ya guardados |
| `rfp-ui-formal.png` | ModaViva (`trackflow-request-1.pdf`): `analisis_completo`, `warehouse` (Ana Whitfield) + `reverse` (Sofía Ramos), EUR, `lastmile` excluido explícitamente, integración ERP a Miguel Torres |
| `rfp-ui-informal.png` | Luna Cosmetics (`trackflow-request-2.pdf`): `analisis_completo`, `warehouse` (Ana Whitfield) + `lastmile` (Carlos Vega), USD, 5.000 pedidos/mes, fecha sin año como texto |
| `rfp-ui-invalido.png` | RapidShip (`trackflow-request-3.pdf`): `descartado` como `vendor_pitch` (LLM 99 %, reglas de acuerdo) |
| `ticket-1-modaviva.json`, `ticket-2-luna.json`, `ticket-3-rapidship.json` | Resultado guardado de cada ticket (`scripts/rfp_intake_run.py --show <n> --out …`): clasificación, metadatos, legibilidad y handoff `trackflow.rfp_intake.handoff/v1` |

Resultado con el LLM de 4Geeks: en los tres casos el clasificador LLM y las reglas coinciden; las guardas no tuvieron que descartar ningún dato (`warnings` vacíos) y no hay contradicciones (`conflicts` vacío).
