# Evidencia de lazy loading — Fase 5

## Implementación

| Aplicación | Componente | Cuándo se solicita |
|---|---|---|
| Website | `LazyLeadForm` → `LeadForm` | Al aproximarse al viewport (`IntersectionObserver`, `rootMargin: 300px`) o al navegar al ancla `#contacto`. El título, el texto y el ancla se renderizan desde el wrapper; solo se difiere el formulario. |
| Application | `AnalysisResults` | Solo cuando el análisis termina correctamente y existen resultados (`uiState === 'success' && result`). No se precarga al seleccionar el fichero. |

El placeholder del formulario reserva `min-h-[75rem]` en móvil y `min-h-[49rem]` desde `md`. Son estimaciones estáticas, no una medición de altura renderizada; no se pudo verificar CLS visualmente en navegador.

## Builds

- Website: OK con Next.js 16.2.11; salida en [build-after-website.txt](./build-after-website.txt).
- Application: OK con Next.js 16.2.11; salida en [build-after-application.txt](./build-after-application.txt).
- Turbopack no muestra tamaños de JavaScript por ruta en estas salidas.

## Chunks

| Componente | Archivo del chunk | Tamaño |
|---|---|---|
| `LeadForm` | Pendiente | Pendiente |
| `AnalysisResults` | Pendiente | Pendiente |

La inspección de `.next/static/chunks` fue denegada por la política de exclusión de la organización. No se intentó acceder a esos archivos por otra vía ni se estimaron nombres o tamaños. Marisin puede completar esta tabla con la evidencia de su terminal.

## Verificación manual (Marisin)

1. Abrir DevTools → Network → JS y recargar la landing. Comprobar que el chunk del formulario no se solicita inicialmente y aparece al hacer scroll hacia el formulario.
2. Abrir `/incidents/analyze`, observar Network → JS, seleccionar un fichero y confirmar que todavía no se solicita el chunk de resultados.
3. Ejecutar el análisis y comprobar que el chunk de resultados se solicita después del éxito.
4. Verificar visualmente el espacio reservado del formulario y CLS en móvil y escritorio. Añadir capturas en `docs/caching/frontend/`.
