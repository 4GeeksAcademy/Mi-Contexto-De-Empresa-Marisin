# Endpoint benchmark — 03-after-cache

- Fecha/hora UTC: 2026-11-17T17:17:01+00:00
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
| `/inventory/products` | 334.4 ms / 47.92 KB (MISS) | 3.4 | 5.6 | 12.9 | 14.9 | 47.92 | HIT=30, MISS=0, BYPASS=0, ausente=0 |
| `/inventory/orders` | 862.7 ms / 2366.74 KB (ausente) | 392.5 | 416.9 | 589.9 | 650.6 | 2366.74 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/inventory/products/2` | 147.1 ms / 0.15 KB (ausente) | 122.2 | 131.1 | 138.9 | 141.5 | 0.15 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/api/incidents` | 28.9 ms / 929.27 KB (ausente) | 19.4 | 27.8 | 41.8 | 42.1 | 929.27 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/api/incidents/summary` | 27.0 ms / 0.31 KB (MISS) | 0.5 | 0.7 | 2.1 | 2.5 | 0.31 | HIT=30, MISS=0, BYPASS=0, ausente=0 |
| `/suppliers` | 15.2 ms / 0.27 KB (ausente) | 14.1 | 17.2 | 26.8 | 34.6 | 0.27 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
