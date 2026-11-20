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
