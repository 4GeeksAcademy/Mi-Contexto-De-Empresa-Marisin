# Codebase Audit & Web Performance Analysis (AUDIT.md)

## Resumen ejecutivo
Esta auditoría documenta las mediciones de Lighthouse del website y el backoffice, además de los problemas de rendimiento que se verificarán con cambios y mediciones posteriores.

El baseline corresponde al commit `98e1b1b7f1c1c71b672ed211eb5b639ea84c1d70` y se midió en producción (`build` + `start`), no en `next dev`. Fecha de medición: 12 de noviembre de 2026. Lighthouse se ejecutó en Chrome incógnito, mediante las URLs reenviadas de Codespaces para los puertos 3000/3001, con la API en el puerto 8000. La conexión reenviada añade latencia; las mediciones posteriores deberán usar el mismo entorno. Se utilizaron los presets Desktop y Mobile; sus dimensiones numéricas no están registradas.

---

## 1. Métricas baseline de Lighthouse

| Aplicación / ruta | Modo | Performance | Accessibility | Best Practices | SEO | FCP | LCP | TBT | CLS | Speed Index | INP | TTFB |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- |
| Website `/` | Desktop | 99 | 85 | 96 | 60 | 0,6 s | 0,8 s | 0 ms | 0 | 0,8 s | No capturado | No capturado |
| Website `/` | Mobile | 98 | 85 | 96 | 60 | 1,0 s | 2,0 s | 130 ms | 0 | 2,1 s | No capturado | No capturado |
| Backoffice `/inventory/products` (sesión iniciada) | Desktop | 100 | 88 | 96 | 40 | 0,3 s | 0,5 s | 0 ms | 0 | 0,9 s | No capturado | No capturado |
| Backoffice `/inventory/products` (sesión iniciada) | Mobile | 100 | 88 | 96 | 40 | 0,8 s | 1,7 s | 60 ms | 0 | 1,6 s | No capturado | No capturado |

TBT es la métrica de bloqueo registrada. INP y TTFB no fueron capturados y no se estiman.

---

## 2. Hallazgos verificados y pendientes de medir

### LCP del hero del website
- **Síntoma medido:** En el baseline móvil, LCP fue 2,0 s; en desktop, 0,8 s.
- **Evidencia:** El `h1` está dentro de un contenedor `.fade-up` (`uis/website/components/Hero.tsx:4`); con movimiento habilitado, `uis/website/app/globals.css:59-60` aplica una animación de 0,7 s cuya clave inicial fija `opacity: 0` (`uis/website/app/globals.css:76-79`).
- **Causa probable:** La opacidad inicial puede retrasar la presentación del contenido que contiene el LCP. Es una hipótesis apoyada por el código, todavía no un resultado medido.
- **Cambio/métrica:** Pendiente de aplicar la corrección y volver a medir con el mismo Lighthouse, ruta, viewport y entorno. No se afirma una mejora todavía.

### Estado de carga de productos
- **Síntoma:** Mientras se cargan los productos, la página devuelve solo el texto “Cargando inventario de TrackFlow...” (`uis/backoffice/src/app/inventory/products/page.tsx:26-27`), sin mostrar el encabezado ni la estructura de la tabla.
- **Causa probable:** El contenido inicial puede cambiar de forma al llegar los datos. Sin embargo, el CLS baseline fue 0 en ambos viewports, así que no hay evidencia de un problema de CLS en esa medición.
- **Cambio/métrica:** Un skeleton de altura estable es una opción a medir; no se presentará como mejora si LCP/CLS no mejora.

### SEO y accesibilidad
- **Síntoma medido:** SEO fue 60 en website y 40 en backoffice; Accessibility fue 85 y 88, respectivamente.
- **Causa:** No atribuida todavía. No se cuenta con la lista de auditorías fallidas de Lighthouse que permita identificar causas. Tampoco se inferirá que los metadatos explican el SEO ni que existe un defecto de accesibilidad por la puntuación agregada.
- **Siguiente paso:** Inspeccionar los audits concretos antes de cambiar SEO o accesibilidad. En el backoffice, verificar además si alguna directiva de no-indexación es intencional.

### Alcance del cambio de `tsconfig`
El baseline tenía `target: ES2017` en ambas aplicaciones y la entrega lo cambió a `ES2022`. Ese cambio no demuestra que Next.js haya eliminado polyfills ni que haya reducido TBT; se retira esa explicación causal y no se considera una optimización de rendimiento.

## 3. Casos reales de duplicación

### Caso 1: tarjetas con KPIs
- **Dónde aparece:** El hero del website muestra tres métricas con estructura de tarjeta en `uis/website/components/Hero.tsx:26-38`. `uis/application/components/OperationsPanel.tsx:100-107` renderiza tarjetas `KpiCard`, cuya implementación privada está en `uis/application/components/OperationsPanel.tsx:178-185`.
- **Por qué es candidato:** Ambos presentan una etiqueta/valor y contexto de métricas operativas. No son componentes idénticos: el hero usa contenido de marketing y otra estructura visual, mientras que el panel muestra datos dinámicos.
- **Abstracción propuesta:** Crear `packages/shared/components/StatCard.tsx` con la firma `type StatCardProps = { title: string; value: string; detail?: string }; export function StatCard({ title, value, detail }: StatCardProps)`. La usarían `uis/website/components/Hero.tsx` para las tres métricas del hero y `uis/application/components/OperationsPanel.tsx` en lugar de su `KpiCard` local. El componente no existe actualmente; esta es una propuesta, no una implementación.

### Caso 2: ciclo de fetch, loading y error
- **Dónde aparece:** La página de productos carga con `getProducts()` y actualiza `loading`/`error` en `uis/backoffice/src/app/inventory/products/page.tsx:15-27`. El historial de órdenes repite el patrón con `getOrders()` en `uis/backoffice/src/app/inventory/orders/page.tsx:12-23`.
- **Por qué es candidato:** Ambas páginas mantienen el mismo ciclo de carga asíncrona, transición de estado y presentación de error, aunque consuman endpoints y tipos distintos.
- **Abstracción:** Un hook tipado `useInventoryData` podría encapsular `data`, `loading` y `error`, recibiendo la función de carga de cada página. Aún no existe; solo se considerará resuelto cuando esté implementado, importado y usado en ambas páginas.

## 4. Entorno de medición

El baseline se tomó sobre builds de producción (`build` + `start`), no sobre `next dev`, en Chrome incógnito, usando las URLs reenviadas de Codespaces y la API en el puerto 8000. La latencia de la URL reenviada forma parte del entorno y deberá mantenerse para la comparación posterior. No hay TTFB ni INP capturados.

## 5. Cambios no relacionados con rendimiento

- `uis/backoffice/src/app/page.tsx:4` redirige `/` a `/login`. Es un cambio de navegación y no se presenta como una mejora de rendimiento.
- `uis/backoffice/src/app/inventory/orders/outbound/page.tsx:27-32` calcula el stock disponible sumando movimientos del producto seleccionado filtrados por almacén. Es un cambio funcional y no se presenta como una mejora de rendimiento.

## Trabajo futuro

- Revisar si hay cambios de CLS en `uis/application` con una medición reproducible y evidencia verificable.