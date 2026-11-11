# Informe de Auditoría y Optimización de Rendimiento (REPORT.md)

## Resumen Ejecutivo
Este informe documenta los resultados finales, las ganancias de rendimiento, la refactorización arquitectónica y las evidencias del uso de agentes de IA a lo largo de los frontends del monorepo **TrackFlow** (`uis/website` y `uis/backoffice`).

Todas las auditorías se ejecutaron estrictamente sobre **builds de producción** (`npm run build` + `npm run start`) servidos en los puertos 3000 y 3001 dentro de sesiones limpias de Chrome Incógnito[cite: 19].

La sección 6 añade una medición local posterior de los cuatro servicios compilados activos. Sus resultados usan Chromium headless sin throttling y deben leerse aparte de la comparativa histórica Lighthouse de las secciones anteriores.

---

## 1. Comparativa de Métricas (Baseline vs. Post-Optimización)

### Tabla Resumen

| Aplicación y Entorno | Puntuación Baseline | Baseline LCP | Baseline TBT | Puntuación Optimizada | LCP Optimizado | TBT Optimizado | Estado |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Website (`:3000`) — Escritorio** | 98 | 0.9s | 0ms | **100** | **0.4s** | **0ms** | Cumplido (Puntuación 100) |
| **Website (`:3000`) — Móvil** | 97 | 2.1s | 130ms | **98** | **2.2s** | **80ms** | Cumplido (Reducción de TBT) |
| **Backoffice (`:3001`) — Escritorio** | 98 | 1.15s | 0ms | **100** | **0.5s** | **0ms** | Cumplido (Puntuación 100) |
| **Backoffice (`:3001`) — Móvil** | 74 | 5.3s | 300ms | **99** | **1.8s** | **80ms** | **Gran Victoria (LCP 5.3s → 1.8s)** |

---

## 2. Principales Mejoras y Solución de Problemas Reales

### 1. Solución del Cuello de Botella en Backoffice Móvil (LCP 5.3s → 1.8s / TBT 300ms → 80ms)
- **Causa Raíz Resuelta:** Ejecución síncrona sobrecargada en el hilo principal durante el renderizado de datos y competencia en la carga de fuentes.
- **Impacto:** Eliminar los envoltorios de transpilación innecesarios de ES2020 permitió al motor del navegador parsear y ejecutar los chunks de JavaScript más rápido bajo perfiles de CPU restringidos. El LCP se redujo un **66%** y el TBT un **73%**, elevando la puntuación de rendimiento móvil de **74 a 99**.

### 2. Cumplimiento de Estándares de SEO y Accesibilidad
- **Causa Raíz Resuelta:** Ausencia de metadatos a nivel de documento (`<title>` y `<meta name="description">`) en el layout raíz de `backoffice`.
- **Impacto:** Se inyectaron estructuras declarativas de metadatos estáticos en `uis/backoffice/src/app/layout.tsx`. La puntuación de Accesibilidad de Backoffice aumentó de **88 a 93**, estableciendo una estructura de SEO completa en ambas aplicaciones.

### 3. Modernización del Target de JavaScript (ES2017/ES2020 → ES2022)
- **Causa Raíz Resuelta:** Targets desactualizados en TypeScript que forzaban polyfills y funciones envolventes para sintaxis moderna (como *optional chaining* o campos de clase).
- **Impacto:** Se actualizaron los targets en `tsconfig.json` en ambas aplicaciones del workspace (`uis/website` y `uis/backoffice`), disminuyendo el tamaño total del bundle procesado y alcanzando puntuaciones máximas de rendimiento en escritorio (**100**) en ambos frontends.

---

## 3. Refactorización de Código y Arquitectura Compartida

### Componente Abstraído: Reutilización de Tarjeta de Métricas / Estado (`StatCard`)
- **Estrategia de Refactorización:** Se aisló la lógica de renderizado visual de métricas (anteriormente duplicada entre los KPIs de marketing y los resúmenes operativos de inventario) en la capa compartida del monorepo (`shared/` / `@repo/shared`)[cite: 19, 21].
- **Integridad y Calidad:** Ambas aplicaciones compilan sin regresiones, errores de tipo ni fallos en la estructura del layout (validado mediante `npm run build`).

---

## 4. Evidencias de Uso de Skills y Agentes

- **Evidencia de Uso de Skills:** Se utilizaron las capacidades de inspección del agente para analizar las características de los builds de producción de Next.js y las dependencias en runtime (`node_modules/next/dist/docs`).
- **Gestión de Contexto:** Las instrucciones de ejecución y los registros de decisiones arquitectónicas se almacenaron en `plaincontext.md` y se archivaron en `memory-bank/history/2026-11-10_refactor-performance.md` para garantizar una trazabilidad y auditoría completas.

---

## 5. Estado de Entregables y Artefactos

- [x] `/audit/before/` — Capturas de pantalla iniciales guardadas y commiteadas.
- [x] `/audit/after/` — Capturas de pantalla post-optimización guardadas y commiteadas.
- [x] `AUDIT.md` — Análisis detallado de causa raíz y baseline inicial documentados.
- [x] `REPORT.md` — Informe comparativo final generado.

## 6. Medición Actual de los Cuatro Servicios (2026-11-11)

Medianas de tres cargas con caché HTTP limpia, en Chromium 158 headless y sin throttling de CPU/red. Viewports: escritorio 1365 × 768 y móvil 390 × 844, sin emulación de hardware móvil.

| Servicio y ruta | Viewport | LCP p50 | CLS p50 | Interacción sintética p50* |
| :--- | :--- | ---: | ---: | ---: |
| `uis/application` (`:3004/`) | Escritorio | 180 ms | 0,000 | 16 ms |
| `uis/application` (`:3004/`) | Móvil | 168 ms | **0,385** | 16 ms |
| `uis/backoffice` (`:3005/login`) | Escritorio | 180 ms | 0,000 | 16 ms |
| `uis/backoffice` (`:3005/login`) | Móvil | 148 ms | 0,000 | 16 ms |
| `uis/talent-pipeline-tracker` (`:3002/`) | Escritorio | 164 ms | 0,000 | 24 ms |
| `uis/talent-pipeline-tracker` (`:3002/`) | Móvil | 148 ms | 0,000 | 16 ms |
| `uis/website` (`:3003/`) | Escritorio | 224 ms | 0,000 | 16 ms |
| `uis/website` (`:3003/`) | Móvil | 188 ms | 0,000 | N/D |

\* Una acción automatizada por carga sobre un control visible, medida con Event Timing. Es una referencia sintética de laboratorio, no INP de campo ni datos CrUX/RUM. `N/D` significa que no se observó un evento reportable. Estos valores no son directamente comparables con los resultados Lighthouse anteriores porque no se aplicó throttling.

El CLS móvil de `uis/application` (0,385) supera el umbral de referencia de 0,1 y queda señalado para investigación. No se modifica la puntuación Lighthouse histórica ni se presenta el INP sintético como un dato de usuarios reales.