# Evidencia de lazy loading — Fase 5

## Implementación

| Aplicación | Componente | Cuándo se solicita |
|---|---|---|
| Website | `LazyLeadForm` → `LeadForm` | Al aproximarse al viewport (`IntersectionObserver`, `rootMargin: 300px`) o al navegar al ancla `#contacto`. El título, el texto y el ancla se renderizan desde el wrapper; solo se difiere el formulario. |
| Application | `AnalysisResults` | Solo cuando el análisis termina correctamente y existen resultados (`uiState === 'success' && result`). No se precarga al seleccionar el fichero. |

## Altura reservada del formulario

Marisin midió la altura renderizada del formulario en el navegador con:

```js
Math.round(document.querySelector('#contacto form').getBoundingClientRect().height)
```

| Vista | Altura medida por Marisin | Placeholder ajustado |
|---|---:|---|
| Móvil (ancho 390 px) | 1312 px | `min-h-[82rem]` |
| Escritorio | 808 px | `md:min-h-[50.5rem]` |

Evidencia: [medición en consola](./form-height-console.png). Estas medidas sustituyen las estimaciones anteriores de 75rem y 49rem; la equivalencia entre rem y px corresponde a una raíz de 16 px. El encabezado permanece fuera del placeholder.

CLS **no medido**: reservar la altura medida no demuestra por sí solo la ausencia de desplazamientos de diseño en todas las condiciones.

## Builds

- Website: OK con Next.js 16.2.11; repetido tras ajustar la altura con `NODE_ENV=production npm run build` desde `uis/website`. Salida en [build-after-website.txt](./build-after-website.txt).
- Application: OK con Next.js 16.2.11; se conserva el build ya validado, sin cambios adicionales en esta aplicación. Salida en [build-after-application.txt](./build-after-application.txt).
- Turbopack no muestra tamaños de JavaScript por ruta en estas salidas.

## Chunks

| Componente | Archivo del chunk | Tamaño del archivo (bytes) | Tamaño (KB, base 1000) |
|---|---|---:|---:|
| `LeadForm` | `0ga_n3dnecyt3.js` | 8272 | 8.272 |
| `AnalysisResults` | `0j7qwszrv_mca.js` | 3643 | 3.643 |

Fuente: [salida de terminal aportada por Marisin](./chunks-after.txt). Son tamaños de archivo, no bytes transferidos comprimidos ni tamaños totales de JavaScript por ruta. Los nombres corresponden al build de las capturas y pueden cambiar entre builds.

La inspección de `.next/static/chunks` por el agente fue denegada por la política de exclusión de la organización. No se accedió por otra vía; esta tabla utiliza exclusivamente la evidencia aportada por Marisin.

## Verificación manual (Marisin)

### Evidencia obtenida

- [Website, carga inicial](./network-website-1.png): 6 solicitudes JS, sin el chunk de `LeadForm`.
- [Website, tras hacer scroll al formulario](./network-website-2.png): aparece la solicitud de `0ga_n3dnecyt3.js`.
- [Application, análisis ejecutado](./network-application.png): Marisin observó 9 solicitudes JS iniciales; al ejecutar el análisis se solicita `0j7qwszrv_mca.js`, visible con los resultados.
- [Alturas en consola](./form-height-console.png): 808 px en escritorio y 1312 px en móvil de ancho 390 px, medidos por Marisin.

Las capturas de Network acreditan la carga bajo demanda; la captura de consola acredita las alturas, no una medición de CLS. Son evidencia anterior al ajuste de altura; después del ajuste se repitió el build de website, no la sesión de navegador.

### Pasos para reproducir

1. Abrir DevTools → Network → JS y recargar la landing. Comprobar que el chunk del formulario no se solicita inicialmente y aparece al hacer scroll hacia el formulario.
2. Abrir `/incidents/analyze`, observar Network → JS, seleccionar un fichero y confirmar que todavía no se solicita el chunk de resultados.
3. Ejecutar el análisis y comprobar que el chunk de resultados se solicita después del éxito.
4. Comprobar el espacio reservado en móvil y escritorio. Para verificar CLS hace falta una medición específica de rendimiento; las capturas actuales no la incluyen.
