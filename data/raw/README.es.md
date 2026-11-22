# Carpeta `data/raw`

Esta carpeta está pensada para almacenar **datos en bruto** (raw) relacionados con la compañía: dumps, exports, archivos de ejemplo, muestras de eventos, o datasets sin transformar.

- **Propósito principal**: servir como zona de aterrizaje o referencia de datos originales antes de ser procesados por pipelines.
- **Recomendación**: documenta el origen de cada dataset, formato, tamaño esperado, consideraciones de privacidad/PII y cómo se versiona (idealmente evitando subir datos sensibles al repositorio).

## `trackflow_sales.csv` — histórico mensual de ingresos (predicción de ventas)

- **Origen:** syllabus de 4Geeks, `content/contexts/sales-forecasting/trackflow/trackflow_sales.csv` (BRIEFING de sales-forecasting de TrackFlow). Copiado **sin alterar**: no se regenera ni se simula.
- **Formato:** CSV, 120 filas mensuales (2016-01 → 2025-12), solo `market = consolidated`. Columnas: `month` (`YYYY-MM-01`), `revenue_eur`, `shipments_processed`, `avg_revenue_per_shipment_eur`, `market`.
- **Patrones:** crecimiento anual que alterna ~9 % / ~3 %; pico de noviembre-diciembre (+25-35 %) y valle de febrero (-10-15 %). Generado con `random_state=42`.
- **PII:** ninguna (datos agregados de la empresa).
- **Uso:** `scripts/sales_forecast.py` (ver `docs/sales-forecast/README.md`).

## `rfp/` — PDFs de RFPs subidos desde el backoffice (Hito 9)

- **Origen:** la página **RFPs** del backoffice (`POST /rfp/tickets`). Cada PDF se guarda como `data/raw/rfp/<rfp_id>.pdf` (UUID del ticket; el nombre original queda en `rfp_tickets.original_filename`). Es un artefacto runtime de la recepción: **no se versiona** (`.gitignore`) y los PDF de muestra del BRIEFING no se pre-siembran aquí, se suben por la UI.
- **Formato:** PDF (máx. 10 MB). El Markdown convertido con MarkItDown vive en PostgreSQL (`rfp_tickets.markdown`), no en disco.
- **PII:** contactos de clientes (nombre, cargo, email) como en cualquier RFP real; no subir documentos con datos sensibles.
- **Uso:** `data/pipelines/rfp_intake/` (diseño en `docs/rfp-intake/rfp-intake-design.md`).
