# Evidencias — Flujo agéntico de RFPs · Parte 1

Capturas y exportaciones de la verificación en el Codespace (plan: `memory-bank/history/2026-11-22_rfp-intake.md` §4).

| Fichero | Qué muestra |
|---|---|
| `rfp-tests-pipelines.png` | Tests del clasificador, workers, metadatos, orquestador, synthesizer, grafo y almacén SQL |
| `rfp-tests-routes.png` | Tests de los endpoints y del contrato de rutas (46) |
| `rfp-supabase-tables.png` | Consulta de verificación de las tres tablas en Supabase |
| `rfp-ui-formal.png` | ModaViva (`trackflow-request-1.pdf`): `analisis_completo`, `warehouse` + `reverse`, EUR |
| `rfp-ui-informal.png` | Luna Cosmetics (`trackflow-request-2.pdf`): `analisis_completo`, `warehouse` + `lastmile`, USD |
| `rfp-ui-invalido.png` | RapidShip (`trackflow-request-3.pdf`): `descartado` con el motivo del clasificador |
| `rfp-api-async.png` | Terminal de la API: `POST /rfp/tickets → 202` en milisegundos y el ticket terminando después |
| `ticket-<n>.json` | Resultado guardado de cada ticket (`scripts/rfp_intake_run.py --show <n> --out …`) |
