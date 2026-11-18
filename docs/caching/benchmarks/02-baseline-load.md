# Endpoint benchmark — 02-baseline-load

- Fecha/hora UTC: 2026-11-17T16:19:50+00:00
- Base URL: `http://127.0.0.1:8000`
- Repeticiones tras la primera petición fría: 30
- Latencia: cabecera `X-Response-Time-ms` emitida por la API.

## Volumen de datos

| Tipo | Registros |
|---|---:|
| Productos | 302 |
| Órdenes | 12008 |
| Incidencias | 3000 |

## Resultados

La columna fría informa latencia, tamaño y `X-Cache` de la primera petición.
Las estadísticas min/p50/p95/max, tamaño KB medio y contadores `X-Cache`
corresponden a las 30 peticiones siguientes.

| Endpoint | Primera (fría) | Min ms | p50 ms | p95 ms | Max ms | Media KB | X-Cache (repeticiones) |
|---|---:|---:|---:|---:|---:|---:|---|
| `/inventory/products` | 210.2 ms / 47.92 KB (ausente) | 142.4 | 156.1 | 186.3 | 187.3 | 47.92 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/inventory/orders` | 430.8 ms / 2366.74 KB (ausente) | 399.3 | 416.4 | 459.5 | 473.3 | 2366.74 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/inventory/products/2` | 135.5 ms / 0.15 KB (ausente) | 122.7 | 132.3 | 140.7 | 144.5 | 0.15 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/api/incidents` | 32.8 ms / 929.27 KB (ausente) | 20.6 | 25.8 | 44.1 | 47.1 | 929.27 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/api/incidents/summary` | 35.0 ms / 0.31 KB (ausente) | 18.1 | 22.0 | 41.5 | 47.5 | 0.31 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/suppliers` | 15.6 ms / 0.27 KB (ausente) | 14.2 | 18.5 | 28.0 | 36.8 | 0.27 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
