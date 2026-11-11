# Codebase Audit & Web Performance Analysis (AUDIT.md)

## Executive Summary
Este documento proporciona una auditoría detallada de rendimiento, arquitectura y diagnóstico para las aplicaciones frontend del monorepo **TrackFlow** (`uis/website` y `uis/backoffice`)[cite: 19]. Incluye las métricas de partida (*baseline*) obtenidas con Lighthouse en entornos de producción (`npm run build` + `npm run start`), el análisis técnico de causa raíz de cada cuello de botella y la estrategia de refactorización de código[cite: 19, 30].

La tabla histórica de Lighthouse que sigue cubre solo website y backoffice. Las mediciones actuales de los cuatro servicios compilados se documentan en la sección 5 y no son directamente comparables con ese baseline.

---

## 1. Initial Lighthouse Baseline Metrics

Las mediciones iniciales se realizaron sobre servidores de producción para garantizar un entorno exento de la sobrecarga del entorno de desarrollo (`next dev`)[cite: 19].

| Aplicación / Vista | Modo | Performance | LCP | TBT | CLS | Accessibility | Best Practices | SEO |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Website (`:3000/`)** | Desktop | **98** | 0.9s | 0ms | 0 | 85 | 100 | 60 |
| **Website (`:3000/`)** | Mobile | **97** | 2.1s | 130ms | 0 | 85 | 100 | 60 |
| **Backoffice (`:3001/inventory/products`)** | Desktop | **98** | 1.15s | 0ms | 0 | 88 | 100 | 40 |
| **Backoffice (`:3001/inventory/products`)** | Mobile | **74** ⚠️ | **5.3s** ⚠️ | **300ms** ⚠️ | 0 | 88 | 100 | 40 |

---

## 2. Diagnóstico Técnico y Análisis de Causa Raíz

En lugar de enumerar únicamente las advertencias generadas por la herramienta, a continuación se detallan las razones arquitectónicas y de compilación que originaron las degradaciones observadas[cite: 30]:

### Problema 1: Degradación Severa de LCP (5.3s) y TBT (300ms) en Backoffice Móvil
- **Síntoma:** El indicador LCP en la vista `/inventory/products` móvil alcanza los 5.3s[cite: 27], penalizando la puntuación general hasta 74[cite: 27].
- **Causa Raíz Identificada:**
  1. **Sobrecarga de Transpilación JavaScript (`target: ES2017/ES2020`):** La configuración por defecto en `tsconfig.json` forzaba al compilador de Next.js (SWC) a generar funciones envolventes y *polyfills* de sintaxis moderna (operador *optional chaining*, *nullish coalescing*, etc.). Esto infló el tamaño del *bundle* JavaScript parsed en el hilo principal del móvil, aumentando la latencia de ejecución (*Total Blocking Time*).
  2. **Renderizado de la Tabla sin Bloqueo Gradual:** El listado de SKUs e inventario realizaba el renderizado de forma síncrona en hidratación antes de liberar el hilo de pintado del elemento de mayor tamaño (LCP).

### Problema 2: Puntuación Bajas de SEO (60 en Website / 40 en Backoffice)
- **Síntoma:** Audits deficientes en los motores de búsqueda a pesar de tener una estructura visual correcta[cite: 26, 28].
- **Causa Raíz Identificada:**
  1. **Ausencia de Metadatos Declarativos:** El archivo `layout.tsx` de `backoffice` carecía de las exportaciones de `Metadata` de Next.js (`<title>` y `<meta name="description">`), impidiendo la indexación correcta del documento inicial.
  2. **Etiquetas semánticas incompletas:** Falta de directivas de indexación explícitas en las cabeceras HTML de la aplicación corporativa.

### Problema 3: Oportunidades de Accesibilidad y Fuentes (85 - 88)
- **Síntoma:** Contrastes leves y pequeños retrasos en el intercambio de fuentes tipográficas[cite: 26, 28].
- **Causa Raíz Identificada:**
  1. **Font Display Strategy:** La carga de tipos de letra no declaraba explícitamente el atributo `display: "swap"`, provocando parpadeos o bloqueos breves de renderizado de texto (*FOIT*) durante la inicialización de la página.

---

## 3. Estrategia y Plan de Refactorización de Código

### Caso 1: Abstracción de Componente Reutilizable (`StatCard` / UI Metrics)
- **Ubicación:** Componentes de métricas duplicados conceptualmente en el Landing de `website` y los paneles de inventario del `backoffice`[cite: 19].
- **Justificación de Refactorización:** Extraer la tarjeta de datos a la capa modular compartida (`shared/`) para estandarizar estilos, clases Tailwind y mejorar la mantenibilidad del código entre aplicaciones[cite: 19, 21].

### Caso 2: Modernización del Compilador TypeScript
- **Acción:** Actualizar `"target": "ES2022"` en `uis/website/tsconfig.json` y `uis/backoffice/tsconfig.json`[cite: 19].
- **Justificación:** Los navegadores modernos soportan estas características de forma nativa, lo que elimina código duplicado de *polyfills* y acelera el tiempo de parseo del motor V8/JavaScript.

### Caso 3: Inyección de Metadatos de SEO y Atributos ARIA
- **Acción:** Enriquecer `uis/backoffice/src/app/layout.tsx` con metadatos estructurados (`title`, `description`) y revisar elementos interactivos[cite: 19, 23].

---

## 4. Diferencias de Entorno: `next dev` vs `next start`

> [!IMPORTANT]
> Auditar sobre `next dev` produce métricas de TBT artificialmente elevadas (> 200ms) debido a las verificaciones de React en desarrollo, la inyección del cliente de Hot Module Replacement (HMR) y la falta de minificación SWC. Toda la auditoría del proyecto se basa estrictamente en builds de producción (`next start`)[cite: 19, 29].

## 5. Core Web Vitals de los Builds Activos (2026-11-11)

Se midieron los cuatro servicios compilados actualmente en ejecución. Cada celda representa la mediana de tres cargas con caché HTTP limpia en Chromium 158 headless, sin throttling de CPU ni red. Los viewports fueron 1365 × 768 (escritorio) y 390 × 844 (viewport móvil; sin emulación de hardware móvil).

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

\* La interacción sintética es una única acción automatizada por carga sobre un control visible (`Cargar`, `Iniciar sesion`, `Registrar Candidatura` o `Servicios`). Es una referencia de laboratorio basada en Event Timing, no INP de campo ni datos CrUX/RUM. `N/D` indica que no se capturó un evento reportable en esas muestras. No se asigna puntuación Lighthouse ni se comparan estos resultados locales sin throttling con el baseline histórico.

**Hallazgo:** el CLS móvil medido en `uis/application` (0,385) supera el umbral de referencia de 0,1 y requiere investigación. El resto de los viewports registró CLS 0,000 en estas ejecuciones.