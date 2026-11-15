# Codebase Audit & Web Performance Analysis (AUDIT.md)

## Resumen ejecutivo
Esta auditoría conserva el baseline de Lighthouse y documenta los cambios aplicados: ajuste del hero (`8255f4c`), skeleton de productos (`bf6b388`), extracción de `useInventoryData` (`e736c54`) y restauración del target TypeScript a ES2017 (`894fb1c`). Los resultados posteriores se resumen en [REPORT.md](./REPORT.md).

El baseline corresponde al commit `98e1b1b7f1c1c71b672ed211eb5b639ea84c1d70` y se midió en producción (`build` + `start`), no en `next dev`. Fecha de medición: 12 de noviembre de 2026. Lighthouse se ejecutó en Chrome incógnito, mediante las URLs reenviadas de Codespaces para los puertos 3000/3001, con la API en el puerto 8000. La conexión reenviada añade latencia; las mediciones posteriores se hicieron en el mismo entorno. Se utilizaron los presets Desktop y Mobile; sus dimensiones numéricas no están registradas.

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
- **Evidencia:** Antes de `8255f4c`, el `h1` estaba dentro de un contenedor `.fade-up` (`uis/website/components/Hero.tsx:4`); `git show 8255f4c^:uis/website/app/globals.css` confirma que la animación de 0,7 s iniciaba con `opacity: 0`. La regla actual da al hero una animación sin opacidad inicial (`uis/website/app/globals.css:59-65,91-98`).
- **Causa probable:** La opacidad inicial puede retrasar la presentación del contenido que contiene el LCP. Es una hipótesis apoyada por el código, todavía no un resultado medido.
- **Estado:** Aplicado en `8255f4c`. La variante del hero conserva la transformación, pero ya no inicia con opacidad cero (`uis/website/app/globals.css:63-65,91-98`). Resultados posteriores: [REPORT.md](./REPORT.md).

### Estado de carga de productos
- **Síntoma previo al cambio:** Mientras se cargaban los productos, la página devolvía solo el texto “Cargando inventario de TrackFlow...”, sin mostrar el encabezado ni la estructura de la tabla.
- **Causa probable:** El contenido inicial puede cambiar de forma al llegar los datos. Sin embargo, el CLS baseline fue 0 en ambos viewports, así que no hay evidencia de un problema de CLS en esa medición.
- **Estado:** Aplicado en `bf6b388`. El header y la tabla se mantienen durante la carga con filas skeleton de altura fija (`uis/backoffice/src/app/inventory/products/page.tsx:24-73`). La guía CLS recomienda reservar espacio para contenido asíncrono; no se atribuye al skeleton una mejora de métrica. Resultados posteriores: [REPORT.md](./REPORT.md).

### SEO y accesibilidad
- **Síntoma medido:** SEO fue 60 en website y 40 en backoffice; Accessibility fue 85 y 88, respectivamente.
- **Hipótesis no verificada:** El `title` añadido al layout del backoffice en `975b821` (`uis/backoffice/src/app/layout.tsx:5-9`) pudo influir en ambas puntuaciones, ya que el audit “Document has a <title> element” cuenta en SEO y Accessibility. No se cuenta con la lista de auditorías fallidas para confirmar esta hipótesis ni para atribuir el cambio de cada puntuación.
- **Estado:** Pendiente de verificar las auditorías específicas; no se atribuye una causa confirmada a las puntuaciones.
- **Siguiente paso:** Inspeccionar los audits concretos antes de cambiar SEO o accesibilidad. En el backoffice, verificar además si alguna directiva de no-indexación es intencional.

### Alcance del cambio de `tsconfig`
El baseline tenía `target: ES2017` y `975b821` lo cambió a `ES2022`. **Estado: Aplicado en `894fb1c`**, que restauró `ES2017` en ambas aplicaciones (`uis/website/tsconfig.json:3`; `uis/backoffice/tsconfig.json:3`). No se atribuye a este cambio una mejora de rendimiento ni se afirma que `ES2022` eliminara polyfills o redujera TBT.

## 3. Casos reales de duplicación

### Caso 1: ciclo de carga de inventario (abstracción principal)
- **Dónde aparecía antes de `e736c54`:** En `git show e736c54^:uis/backoffice/src/app/inventory/products/page.tsx`, productos inicializaba `products`, `loading` y `error` en las líneas 10-12 y llamaba `getProducts()` con manejo de éxito/error en las líneas 14-24. En `git show e736c54^:uis/backoffice/src/app/inventory/orders/page.tsx`, órdenes repetía ese patrón con `orders` en las líneas 7-9 y `getOrders()` en las líneas 11-21.
- **Por qué era candidato:** Ambas vistas repetían la gestión de la petición asíncrona, el estado de carga y el error, aunque usaban tipos y funciones de acceso distintos.
- **Estado:** Aplicado en `e736c54` (+48 −34); el ciclo duplicado quedó resuelto. El hook actual expone `data`, `loading` y `error` (`uis/backoffice/src/hooks/useInventoryData.ts:5-38`) y se usa en productos (`uis/backoffice/src/app/inventory/products/page.tsx:9-11`) y órdenes (`uis/backoffice/src/app/inventory/orders/page.tsx:6-8`).

### Caso 2: tarjetas KPI
- **Dónde aparece:** El hero de la website presenta tres tarjetas KPI con valor y detalle (`uis/website/components/Hero.tsx:25-40`). `uis/application` usa `KpiCard` para las métricas de operaciones (`uis/application/components/OperationsPanel.tsx:97-112,178-185`).
- **Por qué es candidato:** Ambos lugares presentan un título, un valor y un detalle en una tarjeta; la estructura visual se repite aunque cada aplicación usa estilos propios.
- **Abstracción propuesta:** Evaluar una abstracción `StatCard` con la firma `type StatCardProps = { title: string; value: string; detail?: string }`.
- **Estado:** Candidato, NO implementado. Añadir resúmenes nuevos a `products`/`orders` sería una funcionalidad nueva, no extraer una duplicación existente.

## 4. Entorno de medición

El baseline se tomó sobre builds de producción (`build` + `start`), no sobre `next dev`, en Chrome incógnito, usando las URLs reenviadas de Codespaces y la API en el puerto 8000. La latencia de la URL reenviada formó parte del entorno y se mantuvo para las mediciones posteriores. No hay TTFB ni INP capturados.

## 5. Cambios no relacionados con rendimiento

- `uis/backoffice/src/app/page.tsx:4` redirige `/` a `/login`. Es un cambio de navegación y no se presenta como una mejora de rendimiento.
- `uis/backoffice/src/app/inventory/orders/outbound/page.tsx:27-32` calcula el stock disponible sumando movimientos del producto seleccionado filtrados por almacén. Es un cambio funcional y no se presenta como una mejora de rendimiento.

## Trabajo futuro

- Revisar si hay cambios de CLS en `uis/application` con una medición reproducible y evidencia verificable.