# Evidencias — Flujo agéntico de RFPs, Parte 3 (aprobación humana y cierre del documento)

Rama `feature/rfp-approval-completion`. Se ejecutan en el Codespace con Supabase (y el LLM de 4Geeks en la UI).
Diseño: `../rfp-approval-design.md`.

## Base de datos y tests

| Evidencia | Qué demuestra |
|---|---|
| `rfp-approval-supabase-columns.png` | `services/sql/005_rfp_approval.sql` aplicado: `rfp_department_sections` 24, `rfp_final_documents` 10, `rfp_metadata` 18, `rfp_trace_events` 13 y `rfp_tickets` 20 columnas. |
| `rfp-approval-tests-pipelines.png` | `pytest tests/pipelines -k rfp_approval -q`: triggers y árbitro del BRIEFING §7, validación de la decisión humana, interrupción y reanudación en el mismo nodo, **aprobar B mientras A sigue interrumpida**, `request_changes` → generador de la Parte 2, límite de rondas, límite de arbitraje, hilos por ticket, reanudación desde SQLite tras «reiniciar», traza y almacén SQL. |
| `rfp-approval-tests-routes.png` | `pytest tests/test_rfp_routes.py tests/test_serialization_contracts.py -q`: recorrido real POST → Partes 1, 2 y 3 → aprobaciones por la API → documento; 422/409 antes de tocar el grafo; contrato de **51** rutas. |
| `rfp-approval-tests-all.png` | `python -m pytest -q`: la suite completa en verde. |

## Ruta E2E reproducible (`scripts/rfp_approval_run.py --e2e all`)

| Evidencia | Qué demuestra |
|---|---|
| `rfp-approval-e2e.png` · `e2e-all.json` | Los cuatro escenarios (Partes 1 → 3 sin BD ni LLM, checkpointer SQLite en disco y un servicio nuevo en cada decisión): `parallel`, `returns`, `volume` y `limit`, con cada comprobación ✓, los `thread_id` por ticket y departamento, la línea de tiempo de estados, el documento final y la traza. |

## UI del backoffice (`/rfp`)

| Evidencia | Qué demuestra |
|---|---|
| `rfp-approval-ui-esperando.png` | Ticket «Esperando aprobación»: cada sección con su formulario y su responsable (solo él firma). |
| `rfp-approval-ui-b-aprobada.png` | Carlos Vega aprueba `lastmile` mientras `warehouse` sigue «Pendiente de aprobación»: no hay documento final. |
| `rfp-approval-ui-cambios.png` | Ana Whitfield pide cambios: el generador reescribe `warehouse` y la sección vuelve a «Pendiente» en la ronda 1. |
| `rfp-approval-ui-terminado.png` | Con las dos aprobadas: ticket «Terminado» y el documento final consolidado para Ventas (descargable en `.md`). |
| `rfp-approval-ui-traza.png` | «Ver traza»: qué agente hizo qué y en qué orden, de `rfp_intake` al `ultimate_document_synthesizer`, con las pausas ⏸. |
| `ticket-<id>-approval.json` | `--show`: estado, aprobaciones con `approver`/`approved_at`, documento final y traza completa del ticket real. |
