# Informe de rendimiento: website y backoffice

## Resumen y metodología

Se comparan Lighthouse antes y después en `uis/website` (`/`, puerto 3000) y `uis/backoffice` (`/inventory/products`, con sesión iniciada, puerto 3001). Las mediciones se hicieron en producción (`build` + `start`), Chrome incógnito, mediante URL reenviada de Codespaces y con la API disponible en el puerto 8000. La latencia añadida por el túnel forma parte de las condiciones.

El baseline corresponde al commit `98e1b1b7f1c1c71b672ed211eb5b639ea84c1d70`. Cada captura representa una ejecución; no se infieren medianas ni distribución. Hay dos capturas posteriores desktop y una mobile de la website. Las capturas posteriores del backoffice se tomaron con un build posterior a `e736c54`. INP y TTFB no se capturaron. Las comparaciones describen los valores observados, pero no aíslan por sí solas el efecto causal de un commit.

En las tablas, puntuaciones en el orden Performance / Accessibility / Best Practices / SEO; métricas en el orden FCP / LCP / TBT / CLS / Speed Index.

## Comparativa antes/después

### Website — `/`

| Modo y ejecución posterior | Antes | Después | Diferencia (después − antes) |
|---|---|---|---|
| Desktop, 14:36 | 99 / 85 / 96 / 60; 0,6 s / 0,8 s / 0 ms / 0 / 0,8 s | 100 / 85 / 96 / 60; 0,4 s / 0,4 s / 0 ms / 0 / 0,4 s | +1 / 0 / 0 / 0; −0,2 s / −0,4 s / 0 ms / 0 / −0,4 s |
| Desktop, 15:21 | 99 / 85 / 96 / 60; 0,6 s / 0,8 s / 0 ms / 0 / 0,8 s | 100 / 85 / 96 / 60; 0,4 s / 0,5 s / 0 ms / 0 / 0,4 s | +1 / 0 / 0 / 0; −0,2 s / −0,3 s / 0 ms / 0 / −0,4 s |
| Mobile, 15:03 | 98 / 85 / 96 / 60; 1,0 s / 2,0 s / 130 ms / 0 / 2,1 s | 99 / 85 / 96 / 60; 1,0 s / 2,0 s / 50 ms / 0 / 1,0 s | +1 / 0 / 0 / 0; 0 s / 0 s / −80 ms / 0 / −1,1 s |

### Backoffice — `/inventory/products` con sesión

| Modo y ejecución posterior | Antes | Después | Diferencia (después − antes) |
|---|---|---|---|
| Desktop, 21:12 | 100 / 88 / 96 / 40; 0,3 s / 0,5 s / 0 ms / 0 / 0,9 s | 100 / 93 / 96 / 60; 0,3 s / 0,5 s / 0 ms / 0,009 / 0,5 s | 0 / +5 / 0 / +20; 0 s / 0 s / 0 ms / +0,009 / −0,4 s |
| Mobile, 21:13 | 100 / 88 / 96 / 40; 0,8 s / 1,7 s / 60 ms / 0 / 1,6 s | 99 / 93 / 96 / 60; 0,8 s / 1,7 s / 80 ms / 0 / 1,5 s | −1 / +5 / 0 / +20; 0 s / 0 s / +20 ms / 0 / −0,1 s |

## Cambios y evidencia

### Hero de la website — [8255f4c](https://github.com/4GeeksAcademy/Mi-Contexto-De-Empresa-Marisin/commit/8255f4c)

- **Síntoma:** el análisis previo observó que la animación `.fade-up` del hero podía ocultar inicialmente el contenido que contiene el H1 ([AUDIT.md](./AUDIT.md), [Hero.tsx](./uis/website/components/Hero.tsx):4, [globals.css](./uis/website/app/globals.css):59-91).
- **Causa considerada:** una opacidad inicial aplicada al contenedor del LCP podía retrasar su presentación; era una hipótesis de código, no una causa probada por traza.
- **Cambio:** se mantuvo el movimiento de transformación y se evitó que la variante del hero comenzara con opacidad cero.
- **Métrica observada:** LCP desktop pasó de 0,8 s a 0,4 s y 0,5 s en las dos capturas posteriores; mobile se mantuvo en 2,0 s. Son diferencias entre capturas y no una atribución causal aislada al commit.
- **Origen:** el análisis del hero provino del feedback del profesor y quedó documentado antes de instalar las skills. Las skills se leyeron después y aportaron metodología de medición y la distinción entre TBT e INP; no originaron este cambio. Más detalle en [audit/skills.md](./audit/skills.md).

### Metadatos del backoffice — [975b821](https://github.com/4GeeksAcademy/Mi-Contexto-De-Empresa-Marisin/commit/975b821)

- **Cambio verificado:** el commit añadió `title` y `description` al metadata del layout ([layout.tsx](./uis/backoffice/src/app/layout.tsx):5-9; comprobado con `git show 975b821`).
- **Métrica observada:** SEO pasó de 40 a 60. La incorporación de título y descripción es un cambio SEO y respalda esa relación; las capturas no permiten atribuir cuánto del cambio corresponde a cada audit.
- **Accesibilidad:** también se observó 88 a 93, pero los metadatos de título/descripción no explican ese cambio. No se atribuye a este commit.
- **Rendimiento:** este cambio no se presenta como optimización de rendimiento.

### Restauración del target TypeScript — [894fb1c](https://github.com/4GeeksAcademy/Mi-Contexto-De-Empresa-Marisin/commit/894fb1c)

- **Cambio:** se restauró `target: ES2017` en ambos `tsconfig.json` ([website](./uis/website/tsconfig.json):3; [backoffice](./uis/backoffice/tsconfig.json):3), el valor del baseline.
- **Métrica:** no se atribuye a este cambio ningún movimiento de Lighthouse. La comparación no demuestra que cambiar el target a ES2022 redujera polyfills, bundle o TBT.

### Skeleton de productos — [bf6b388](https://github.com/4GeeksAcademy/Mi-Contexto-De-Empresa-Marisin/commit/bf6b388)

- **Síntoma:** antes de recibir los productos, el estado de carga no conservaba el encabezado ni la estructura de la tabla.
- **Cambio:** se mantienen header y tabla y se muestran filas skeleton de altura fija ([products/page.tsx](./uis/backoffice/src/app/inventory/products/page.tsx):24-73).
- **Guía:** la referencia CLS recomienda reservar espacio y mantener contenedores estables para contenido asíncrono. El skeleton aplica esa recomendación; la guía no exige específicamente un skeleton.
- **Métrica observada:** CLS desktop pasó de 0 a 0,009; en mobile permaneció en 0. No se atribuye el aumento desktop al skeleton ni se afirma una mejora de CLS. LCP permaneció en 0,5 s desktop y 1,7 s mobile.

### Hook compartido — [e736c54](https://github.com/4GeeksAcademy/Mi-Contexto-De-Empresa-Marisin/commit/e736c54)

- **Cambio:** `useInventoryData` (`data`, `loading`, `error`; función de carga como parámetro) se implementó en [useInventoryData.ts](./uis/backoffice/src/hooks/useInventoryData.ts):5-38 y se usa en [products/page.tsx](./uis/backoffice/src/app/inventory/products/page.tsx):9-11 y [orders/page.tsx](./uis/backoffice/src/app/inventory/orders/page.tsx):6-8.
- **Tamaño del cambio:** el commit registra +48 y −34 líneas netas en su diff.
- **Métrica:** refactor de estado/efectos; no se afirma una mejora medible de Lighthouse.

## Cambios no relacionados con rendimiento

- El cambio de metadata de `975b821` corresponde a SEO; el aumento observado de Accessibility no queda explicado por él ni se atribuye a cambios no comprobados.
- `uis/backoffice/src/app/page.tsx:4` redirige `/` a `/login`; es navegación, no una optimización de rendimiento.
- `uis/backoffice/src/app/inventory/orders/outbound/page.tsx:26-33` calcula stock disponible a partir de movimientos del producto y almacén seleccionados; es lógica funcional.
- El antiguo salto de LCP de 5,3 s a 1,8 s comparaba `next dev` con producción. Al no ser el mismo entorno, no es una comparación válida y no se presenta como resultado de esta auditoría.

## Valoración

La mayor mejora de LCP observada fue en website desktop: de 0,8 s a 0,4 s o 0,5 s según la captura. El LCP mobile de la website no mejoró: siguió en 2,0 s. En el backoffice, LCP se mantuvo en 0,5 s desktop y 1,7 s mobile; el CLS desktop pasó a 0,009, el Performance mobile bajó de 100 a 99 y el TBT mobile subió de 60 ms a 80 ms. Estos cambios observados no prueban causalidad por sí solos.

SEO del backoffice quedó en 60 y Accessibility en 93; ambos conservan margen. No se dispone de las auditorías detalladas para diagnosticar otras causas. INP y TTFB no fueron capturados, por lo que no se concluye sobre esas métricas.
