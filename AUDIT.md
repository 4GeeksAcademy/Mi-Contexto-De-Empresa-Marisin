# Codebase Audit & Web Performance Analysis

## Executive Summary
This document provides a comprehensive performance, architectural audit, and diagnostic report for the TrackFlow monorepo frontends (`uis/backoffice` and `uis/website`). It details initial Lighthouse baseline metrics, regression root cause analysis, Lighthouse audit findings, technical refactoring candidate solutions, and environment benchmarking rules (`next dev` vs `next start`).

---

## 1. Initial Lighthouse Baseline vs. Post-Optimization Metrics

| Frontend Application / View | Baseline Score | Baseline LCP | Baseline TBT | Degraded Audit (LCP / TBT) | Production Optimized Score | Production LCP | Production TBT | Target Status |
|---|---|---|---|---|---|---|---|---|
| **Website (`http://localhost:3000/` - Desktop)** | **98** | **0.9s** | **0ms** | *Pending Fix* | *Pending* | *Pending* | **Met (LCP <= 2.5s, TBT <= 200ms)** |
| **Website (`http://localhost:3000/` - Mobile)** | **97** | **2.1s** | **130ms** | *Pending Fix* | *Pending* | *Pending* | **Met (LCP <= 2.5s, TBT <= 200ms)** |
| **Backoffice (`http://localhost:3001/inventory/products` - Desktop)** | **98** | **1.1s** | **0ms** | *Pending Fix* | *Pending* | *Pending* | **Met (LCP <= 2.5s, TBT <= 200ms)** |
| **Backoffice (`http://localhost:3001/inventory/products` - Mobile)** | **74** | **5.3s** | **300ms** | **5.3s / 300ms** | *Pending* | *Pending* | **Unmet (LCP > 2.5s, TBT > 200ms)** |

> **Nota del Baseline:**
> - **Sitio Corporativo (`website`)**: Accesibilidad en **85**, Best Practices en **100**, SEO en **60** (Desktop & Mobile).
> - **Backoffice (`backoffice`)**: Accesibilidad en **88**, Best Practices en **100**, SEO en **40** (Desktop & Mobile).

---

## 2. Environment Impact: Development Server (`next dev`) vs. Production Server (`next start`)

> [!IMPORTANT]
> Running Lighthouse audits against the Localhost Development Environment (`start.sh` executing `npm run dev`) yields **artificially inflated TBT metrics (> 200ms)** due to dev-mode React assertions and Hot Module Replacement overhead.

### Key Factors Causing High TBT in Development Mode (`next dev` / `start.sh`):
1. **Un-minified React Development Build**: `react-dom/development` executes dev warning checks, prop assertions, and fiber reconciliation validations on every frame.
2. **Fast Refresh & HMR Overhead**: Development mode injects client WebSockets, event listeners, error overlays, and un-optimized inline source maps.
3. **Bypassed SWC Optimizations**: Next.js intentionally disables SWC JavaScript minification and `removeConsole` dead-code elimination in `next dev` to preserve debuggability.
4. **On-Demand Compilation**: The Node process and client main thread compile TypeScript ASTs on the fly during initial page requests.

---

## 3. Diagnóstico y Causa Raíz de Problemas Identificados

### 🔴 Rendimiento & Core Web Vitals (Backoffice en Mobile - LCP 5.3s / TBT 300ms)
- **Causa Raíz:** Renderizado síncrono e intensivo de la tabla de inventario en dispositivos de baja capacidad de cómputo (CPU throttling en móviles). Se procesan y formatean múltiples elementos del DOM de golpe sin paginación o virtualización ligera de listas, sumado a la carga de estilos de componentes no optimizados.
- **Efecto:** El elemento de contenido más grande (*Largest Contentful Paint*) tarda 5.3s en completar su pintado definitivo en pantallas móviles.

### 🟡 Accesibilidad (Score 85 - 88)
- **Causa Raíz:**
  1. Relación de contraste de color insuficiente entre textos secundarios/etiquetas (badges) y sus fondos.
  2. Elementos interactivos (botones/inputs) sin atributos descriptivos explícitos (`aria-label`) en ciertos estados del formulario de contacto e inventario.

### 🔴 SEO (Score 40 - 60)
- **Causa Raíz:**
  1. Presencia de cabecera `X-Robots-Tag: noindex, nofollow` o falta de etiquetas `<meta name="description">` explícitas en las páginas principales.
  2. Falta de elementos semánticos estándar o atributos `alt` completos en elementos gráficos informativos.

---

## 4. Análisis de Refactorización de Código

### Caso 1: Componente de UI Reutilizable — `StatCard` / `KPIBadge`
- **Ubicación:**
  - `uis/website` (Sección "KPIs operativos en tiempo real" en el Landing).
  - `uis/backoffice` (Encabezados de resumen en módulos de inventario/órdenes).
- **Justificación:** Se repite la misma estructura HTML/Tailwind para presentar tarjetas con métricas numéricas, etiquetas superiores y descripciones secundarias.
- **Abstracción propuesta:** Crear un componente compartido reutilizable `StatCard` que acepte las siguientes props: `title`, `value`, `description` y `variant`.

### Caso 2: Custom Hook Reutilizable — `useInventoryData` / `useFetch`
- **Ubicación:**
  - `uis/backoffice/app/inventory/products/page.tsx`
  - `uis/backoffice/app/inventory/orders/page.tsx`
- **Justificación:** Duplicación de lógica para la gestión manual de llamadas asíncronas a la API, estado de carga (`loading`), captura de errores (`error`) y almacenamiento de datos (`data`).
- **Abstracción propuesta:** Extraer la lógica repetida a un Custom Hook `useFetchData<T>(url)` para centralizar la gestión de peticiones, manejo de errores y estados de carga de forma limpia y mantenible.