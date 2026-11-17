# Evidencia de useMemo — Fase 6

## Cambio y justificación

En [OutboundOrderPage](../../../uis/backoffice/src/app/inventory/orders/outbound/page.tsx):

- `selectedProduct` usa `useMemo` con `[products, selectedSkuId]`: la búsqueda no depende de la cantidad, el seguimiento ni el almacén.
- `stockIndex` usa `useMemo` con `[orders]`: recorre el historial y acumula entradas positivas y salidas negativas en un `Map<string, number>` con clave `sku|warehouse`.
- `currentStock` consulta el índice por producto y almacén; devuelve cero si no hay producto o movimientos para esa clave. El lookup es O(1) esperado, sin otro `useMemo`.
- `isStockExceeded` sigue siendo una comparación directa. No se memoizan comparaciones triviales.

Antes se recorría todo `orders` en cada render con un producto seleccionado, aunque solo cambiara un carácter del seguimiento o la cantidad. Después se construye el índice en O(n) al cambiar la referencia de `orders`: al recibir la carga inicial y el historial actualizado tras registrar una salida. Cambiar producto o almacén selecciona otra clave sin recorrer el historial.

Se conservan los mismos signos y agrupación por SKU/almacén, el texto de stock, el aviso, el bloqueo del botón y la recarga con `getOrders().then(setOrders)`. No se modifican peticiones, validaciones de la API ni contratos. La equivalencia de la lógica se revisó en el diff; la comprobación visual en navegador queda pendiente.

El índice requiere memoria adicional O(k), donde k es el número de combinaciones SKU/almacén presentes. La memoización es una optimización local de React, no una caché persistente ni una garantía de frescura del servidor.

## Trabajo antes y después: beneficio estimado

El [benchmark de carga](../benchmarks/02-baseline-load.md) registra **12008 órdenes**; es el volumen medido en esa ejecución, no una nueva consulta realizada en esta fase.

| Situación | Antes | Después |
|---|---|---|
| Carga del historial | Recorrido de las 12008 órdenes en cada render con producto seleccionado | Construcción del índice al cambiar `orders` |
| Edición de seguimiento o cantidad, sin cambiar `orders` | 12008 visitas a órdenes por render con producto seleccionado | Reutilización del índice y lookup de stock |
| Cambio de producto o almacén, sin cambiar `orders` | Otro recorrido del historial | Lookup de la nueva clave |
| Historial recibido tras guardar una salida | Recorrido del historial actualizado | Reconstrucción del índice con ese historial |

Modelo teórico: **12008 × r** visitas a órdenes antes, donde r es el número de renders con producto seleccionado. Para un escenario de 10 renders durante la edición serían **120080 visitas**; después no hace falta recorrer el historial por esas ediciones mientras `orders` no cambie. No se asume que 10 caracteres equivalgan exactamente a 10 renders: React, el modo de desarrollo y otros cambios de estado pueden alterar el recuento.

**Beneficio estimado, no medido con React Profiler.** No hay tiempos de render antes/después ni porcentaje de mejora. El resultado del build no mide rendimiento de interacción.

## Validación

Comando desde `uis/backoffice`:

```sh
NODE_ENV=production NEXT_PUBLIC_INVENTORY_API_URL=http://127.0.0.1:8000 npm run build
```

- [Primer intento](./build-after-backoffice-intento1.txt): compilación, TypeScript y generación de páginas terminados; salida final con código 1 por `SecurityFatalError`, que advierte de una vulnerabilidad conocida de Next.js 16.4.4.
- [Segundo intento](./build-after-backoffice.txt): mismo comando, código 0; compilación, TypeScript y generación de páginas OK. Persiste la advertencia de seguridad y el aviso de múltiples lockfiles.
- Se recomienda actualizar Next.js para corregir la vulnerabilidad; no se cambiaron dependencias porque queda fuera de esta fase.
- No se añadieron tests ni se ejecutaron pytest, benchmarks o servidores. Sin medición de React Profiler ni verificación visual automatizada.

## Verificación manual (Marisin)

1. Comparar la versión anterior al cambio (`f8bba28^`, cierre de Fase 5) con `f8bba28`, usando el mismo modo de ejecución, navegador, dispositivo, datos y producto/almacén. Esta referencia aísla la memoización mejor que `main`; el agente no cambia de rama ni aplica stash.
2. Abrir `/inventory/orders/outbound` con una sesión válida. Esperar a que termine la carga del historial; registrar el volumen real utilizado. Mantener el mismo volumen entre comparaciones.
3. En React DevTools → Profiler, iniciar una grabación y escribir los mismos 10 caracteres en «Número de Seguimiento». Detenerla antes de enviar el formulario.
4. Repetir en la otra versión, con idénticas condiciones y estado inicial. Guardar capturas o exportaciones del Profiler en esta carpeta; anotar número de renders, duración de render del componente y condiciones de cada grabación.
5. Comprobar el mismo stock al cambiar producto y almacén, incluyendo una combinación sin movimientos si existe. Introducir una cantidad superior al saldo y confirmar el mismo aviso y bloqueo del botón.
6. Solo si se autoriza una escritura de prueba, registrar una salida válida y comprobar que el historial recargado actualiza el stock. No crear movimientos reales únicamente para obtener una captura.

Hasta incorporar esas capturas y resultados, el beneficio de interacción y la equivalencia visual permanecen pendientes de verificación manual.
