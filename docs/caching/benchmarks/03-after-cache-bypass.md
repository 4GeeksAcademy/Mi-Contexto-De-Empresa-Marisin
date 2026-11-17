# Endpoint benchmark — 03-after-cache-bypass

- Fecha/hora UTC: 2026-11-17T17:30:58+00:00
- Base URL: `http://127.0.0.1:8000`
- Repeticiones tras la primera petición fría: 30
- Latencia: cabecera `X-Response-Time-ms` emitida por la API.

## Volumen de datos

| Tipo | Registros |
|---|---:|
| Productos | 302 |
| Órdenes | 12008 |
| Incidencias | 3001 |

## Resultados

La columna fría informa latencia, tamaño y `X-Cache` de la primera petición.
Las estadísticas min/p50/p95/max, tamaño KB medio y contadores `X-Cache`
corresponden a las 30 peticiones siguientes.

| Endpoint | Primera (fría) | Min ms | p50 ms | p95 ms | Max ms | Media KB | X-Cache (repeticiones) |
|---|---:|---:|---:|---:|---:|---:|---|
| `/inventory/products` | 194.9 ms / 47.92 KB (BYPASS) | 141.3 | 155.6 | 189.9 | 196.1 | 47.92 | HIT=0, MISS=0, BYPASS=30, ausente=0 |
| `/inventory/orders` | 452.3 ms / 2366.74 KB (ausente) | 398.2 | 418.2 | 465.4 | 515.7 | 2366.74 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/inventory/products/2` | 136.9 ms / 0.15 KB (ausente) | 119.1 | 131.0 | 145.0 | 145.7 | 0.15 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/api/incidents` | 27.8 ms / 929.55 KB (ausente) | 18.7 | 22.7 | 42.8 | 43.2 | 929.55 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
| `/api/incidents/summary` | 16.8 ms / 0.31 KB (BYPASS) | 16.9 | 18.0 | 33.0 | 33.4 | 0.31 | HIT=0, MISS=0, BYPASS=30, ausente=0 |
| `/suppliers` | 14.6 ms / 0.27 KB (ausente) | 12.6 | 13.5 | 22.5 | 30.9 | 0.27 | HIT=0, MISS=0, BYPASS=0, ausente=30 |
