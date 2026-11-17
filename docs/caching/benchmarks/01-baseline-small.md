# Endpoint benchmark — 01-baseline-small

- Fecha/hora UTC: 2026-11-17T15:45:42+00:00
- Base URL: `http://127.0.0.1:8000`
- Repeticiones tras la primera petición fría: 30
- Latencia: cabecera `X-Response-Time-ms` emitida por la API.

## Volumen de datos

| Tipo | Registros |
|---|---:|
| Productos | 2 |
| Órdenes | 8 |
| Incidencias | 0 |

## Resultados

La columna fría informa latencia, tamaño y `X-Cache` de la primera petición.
Las estadísticas min/p50/p95/max, tamaño KB medio y contadores `X-Cache`
corresponden a las 30 peticiones siguientes.

| Endpoint | Primera (fría) | Min ms | p50 ms | p95 ms | Max ms | Media KB | X-Cache (repeticiones) |
|---|---:|---:|---:|---:|---:|---:|---|
| `/inventory/products` | 192.7 ms / 0.30 KB (ausente) | 123.8 | 133.8 | 165.0 | 168.3 | 0.30 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/inventory/orders` | 138.5 ms / 1.50 KB (ausente) | 119.4 | 129.0 | 134.5 | 135.6 | 1.50 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/inventory/products/2` | 127.1 ms / 0.15 KB (ausente) | 118.7 | 128.8 | 137.2 | 138.6 | 0.15 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/api/incidents` | 1.3 ms / 0.00 KB (ausente) | 0.6 | 0.9 | 1.9 | 2.6 | 0.00 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/api/incidents/summary` | 0.8 ms / 0.28 KB (ausente) | 0.6 | 0.9 | 2.7 | 4.3 | 0.28 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/suppliers` | 1.7 ms / 0.27 KB (ausente) | 0.9 | 1.0 | 2.3 | 2.6 | 0.27 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
