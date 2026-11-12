# Auditoría de las skills de rendimiento

## Evidencia de instalación

| Skill | Repositorio | Comando | Fecha | Ubicación | Commit de instalación |
|---|---|---|---|---|---|
| `performance` | `addyosmani/web-quality-skills` | `npx skills add addyosmani/web-quality-skills --skill performance -y` | 12 de noviembre de 2026 | `.agents/skills/performance/` | `4a11cde` |
| `core-web-vitals` | `addyosmani/web-quality-skills` | `npx skills add addyosmani/web-quality-skills --skill core-web-vitals -y` | 12 de noviembre de 2026 | `.agents/skills/core-web-vitals/` | `b6c7388` |

## Alcance y evidencia

Se revisaron las skills `performance` y `core-web-vitals`, incluidas sus referencias de medición, RUM, LCP, CLS e INP, y se inspeccionó el código de `uis/website` y `uis/backoffice`.

La inspección de código produce hipótesis, no fallos medidos. Las capturas Lighthouse existentes son evidencia de laboratorio; no hay CrUX ni RUM disponibles, y no se capturaron trazas de rendimiento ni INP. TBT se conserva como diagnóstico de laboratorio, no como sustituto de INP. TTFB tampoco está registrado.

## Website (`/`)

### Cambio aplicado antes de la lectura de las skills

- **Hero/LCP.** La hipótesis sobre la animación del hero vino del feedback del profesor y quedó en `AUDIT.md` (commit `47ed1d7`), antes de instalar `performance` (`4a11cde`). El cambio `8255f4c` nace de ese análisis: conserva el movimiento de transformación, pero evita la opacidad inicial del contenedor que contiene el H1 ([Hero.tsx](../uis/website/components/Hero.tsx):4; [globals.css](../uis/website/app/globals.css):59-91). Las skills se leyeron después; son compatibles con la decisión, pero no la originaron. Su aporte real fue la metodología para separar datos de campo y laboratorio, repetir mediciones y reportar mediana/rango, además de aclarar que TBT no es INP. En las capturas archivadas, el LCP desktop pasó del valor base de 0,8 s a 0,4 s y 0,5 s; en mobile permaneció en 2,0 s. Son diferencias observadas, no una mejora causal atribuible al commit: las revisiones medidas difieren y no hay trazas equivalentes.

### CORRECCIONES REQUERIDAS

- **No se identifica una corrección requerida por el checklist con la evidencia disponible**: las capturas muestran CLS 0 y los LCP de laboratorio son inferiores a 2,5 s. Esto no acredita los p75 de campo ni permite concluir sobre INP.

### SUGERENCIAS

- Completar una comparación reproducible en producción: misma revisión, URL, estado, navegador, dimensiones, throttling y caché; al menos tres navegaciones equivalentes por viewport. Obtener CrUX de página (o indicar que no está disponible) y traza que desglose LCP/TTFB; medir interacciones por separado antes de hablar de INP. La ruta compone el hero en el render inicial (`uis/website/app/page.tsx:48-59`) y su contenido es texto y tarjetas, no una imagen LCP que requiera preload (`uis/website/components/Hero.tsx:4-25`).
- No se identificaron imágenes locales ni recursos de terceros en el código inspeccionado. Las dos fuentes usan `next/font/google`, subconjunto latino y `display: "swap"` (`uis/website/app/layout.tsx:2-14`); no añadir preconnect/preload sin una traza que muestre descubrimiento tardío o coste de fuente.
- Medir el JavaScript transferido y el coste de la ruta antes de proponer más code-splitting: el formulario es el límite cliente identificado (`uis/website/components/LeadForm.tsx:1,51-54`). No se dispone de tamaños de bundles ni de perfil de CPU.
- El único `<script>` de página es JSON-LD, no una integración de terceros (`uis/website/app/page.tsx:63-66`). No se encontró una corrección de scripts bloqueantes sustentada por las capturas.

### Cambios previos y métricas

- `8255f4c`: mitigó la hipótesis del H1/hero descrita arriba. En desktop se observó LCP 0,8 → 0,4/0,5 s, FCP 0,6 → 0,4 s y Speed Index 0,8 → 0,4 s; en mobile LCP siguió en 2,0 s y FCP en 1,0 s. CLS siguió en 0. No se puede aislar el efecto del cambio con estos datos.
- `975b821`: añadió `display: "swap"` a las fuentes y cambió `target` a ES2022. `display: "swap"` satisface la recomendación de no bloquear texto por fuentes (`uis/website/app/layout.tsx:8,14`), pero ese commit precede a la instalación/revisión de la skill. No hay medición que aísle una métrica movida por estas modificaciones; el cambio de `target` no se cuenta como mejora de rendimiento demostrada.

## Backoffice

### CORRECCIONES REQUERIDAS

- **No se demuestra una corrección obligatoria de CLS**: el baseline documentado para `/inventory/products` registra CLS 0 (`AUDIT.md:16-17`). El estado de carga merece verificación (siguiente sección), pero no se presenta como regresión confirmada.

### SUGERENCIAS

- Medir el cambio de geometría durante la autenticación y la carga de productos. El layout muestra “Verificando sesión...” hasta validar la sesión (`uis/backoffice/src/app/inventory/layout.tsx:10,13-35`), y productos reemplaza el mensaje de carga por el encabezado y la tabla (`uis/backoffice/src/app/inventory/products/page.tsx:11,14-27,78`). Son hipótesis de estabilidad; el baseline de `/inventory/products` registra CLS 0 (`AUDIT.md:16-17`), pero no hay una traza de esos cambios de estado.
- Para INP, ejercitar el inicio de sesión y las acciones de inventario en un dispositivo representativo; no hay interacciones medidas ni datos de campo.
- Medir bundles por ruta antes de añadir imports dinámicos, memoización o virtualización. Las páginas de login e inventario son componentes cliente (`login/page.tsx:1`; `inventory/products/page.tsx:1`), pero no se midieron sus bundles ni se observó una lista de más de 100 productos que justifique virtualizarla.
- La ruta `/inventory/products` con sesión iniciada tiene un baseline distinto, registrado en [AUDIT.md](../AUDIT.md):14-17: LCP 0,5 s desktop y 1,7 s mobile, TBT 0/60 ms y CLS 0. No mezclar sus valores con otras rutas.

### Cambios previos y métricas

- `975b821` actualizó el `target` a ES2022 y añadió metadatos del layout. El target no demuestra reducción de polyfills, TBT ni otra métrica; no se atribuye una mejora de rendimiento a ese commit. Los metadatos son SEO y quedan fuera del alcance de esta revisión.

## Mediciones de la website (Lighthouse)

Valores transcritos de las capturas Lighthouse del 12 de noviembre de 2026. La hora es la que aparece en la captura; no se registró zona horaria. El baseline de [AUDIT.md](../AUDIT.md):6-20 se documentó como build de producción, Chrome incógnito, URL reenviada de Codespaces y presets Desktop/Mobile. Las capturas posteriores son de la misma ruta `/`, pero no anotan versión de Lighthouse, dimensiones numéricas, throttling ni caché; no se puede certificar equivalencia completa de condiciones.

### ANTES

Una ejecución por viewport, correspondiente al baseline:

| Viewport | Hora visible | Captura | Performance | FCP | LCP | TBT | CLS | Speed Index |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| Desktop | 12:16:11 p. m. | [website-desktop.png](./before/website-desktop.png) | 99 | 0,6 s | 0,8 s | 0 ms | 0 | 0,8 s |
| Mobile | 12:13:56 p. m. | [website-mobile.png](./before/website-mobile.png) | 98 | 1,0 s | 2,0 s | 130 ms | 0 | 2,1 s |

### DESPUÉS

Solo ejecuciones con captura archivada en `audit/after/`:

| Viewport | Hora visible | Captura | Performance | FCP | LCP | TBT | CLS | Speed Index |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| Desktop | 2:36:53 p. m. | [website-desktop-run2.png](./after/website-desktop-run2.png) | 100 | 0,4 s | 0,4 s | 0 ms | 0 | 0,4 s |
| Desktop | 3:21:59 p. m. | [website-desktop.png](./after/website-desktop.png) | 100 | 0,4 s | 0,5 s | 0 ms | 0 | 0,4 s |
| Mobile | 3:03:32 p. m. | [website-mobile.png](./after/website-mobile.png) | 99 | 1,0 s | 2,0 s | 50 ms | 0 | 1,0 s |

No se calcula mediana/rango: el baseline tiene una sola ejecución por viewport; después hay dos capturas desktop y una mobile, menos de las tres navegaciones equivalentes recomendadas por la guía. No se deben comparar estos valores de laboratorio con un p75 de campo. INP, TTFB, CrUX/RUM y trazas de diagnóstico siguen sin medirse.

Referencias revisadas: `.agents/skills/performance/SKILL.md` y `references/MEASUREMENT.md`, `references/RUM.md`; `.agents/skills/core-web-vitals/SKILL.md` y `references/LCP.md`, `references/CLS.md`, `references/INP.md`.
