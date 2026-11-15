ROL Y OBJETIVO:
Actúa como un Senior Frontend Performance Engineer & Tech Lead. Tu tarea es ejecutar la fase de optimización, refactorización y resolución de cuellos de botella de rendimiento en las aplicaciones `uis/website` y `uis/backoffice` del monorepo, siguiendo estrictamente la rúbrica y las directrices del archivo `AUDIT.md`.

CONTEXTO Y ARCHIVOS EXISTENTES:
- Ya se realizó el commit de las capturas iniciales en `audit/before/` y de `AUDIT.md`.
- El plan de diagnóstico y baseline se encuentra detallado en `AUDIT.md`.

DIRECTRICES OBLIGATORIAS DE LA RÚBRICA (CUMPLIMIENTO AL 100%):

1. INSTALACIÓN / USO DE SKILLS DE RENDIMIENTO (Si están disponibles en tu entorno):
   - Revisa e integra referencias de análisis basadas en:
     • https://www.skills.sh/addyosmani/web-quality-skills/core-web-vitals
     • https://www.skills.sh/addyosmani/web-quality-skills/performance
     • https://www.skills.sh/cloudflare/skills/web-perf

2. REFACTORIZACIÓN DE CÓDIGO (Componente Reutilizable):
   - Extrae el componente de tarjetas de métricas/KPIs (`StatCard` o `MetricCard`) que se encuentra duplicado o con estructura repetida entre `uis/website` (Landing) y `uis/backoffice` (Inventario/Órdenes).
   - Ubica el nuevo componente en el módulo de código compartido (`shared/` o `@repo/shared` según la arquitectura de paquetes del monorepo).
   - Reemplaza el código anterior en ambas aplicaciones importando el componente compartido abstraído.
   - Realiza un commit exclusivo para esta tarea:
     git add .
     git commit -m "refactor: abstraer componente reutilizable StatCard en shared y reemplazar en website y backoffice"

3. CORRECCIÓN DE RENDIMIENTO Y CORE WEB VITALS (Priorizar TTFB, LCP, CLS, INP):
   A) Optimización de Fuentes y Carga Critica:
      - Configura `display: "swap"` en la carga de fuentes de Next.js (`layout.tsx`).
      - Añade las directivas `<link rel="preconnect" href="https://fonts.googleapis.com" />` y `<link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />` en las cabeceras HTML de ambos frontends.
      - Realiza commit:
        git add .
        git commit -m "perf: agregar preconnect hints y font-display swap en layout principal"

   B) Ajustes de Compilador y Target JS (`tsconfig.json` y `next.config`):
      - Actualiza el target de TypeScript a `"target": "ES2022"` en `uis/website/tsconfig.json` y `uis/backoffice/tsconfig.json` para eliminar polyfills innecesarios de ES2020.
      - En `next.config.mjs` (o `.js`), configura las optimizaciones de minificación e importación de paquetes (`optimizePackageImports`).
      - Realiza commit:
        git add .
        git commit -m "perf: actualizar target a ES2022 y optimizar minificacion en next config"

   C) Mejoras de SEO y Accesibilidad Requeridas:
      - Añade la metaetiqueta de descripción `<meta name="description" ...>` y ajusta los títulos y estructura semántica en las dos aplicaciones para elevar el score de SEO.
      - Añade atributos `aria-label` en botones e iconos sin texto para corregir accesibilidad.
      - Realiza commit:
        git add .
        git commit -m "fix(seo/a11y): agregar metadatos de SEO y etiquetas ARIA en componentes interactivos"

REGLAS DE EJECUCIÓN:
- Mantén la regla estricta: UN PROBLEMA / CORRECCIÓN POR COMMIT [git commit].
- No utilices ni ejecutes comandos de desarrollo (`npm run dev` / `next dev`).
- Verifica que el código compile correctamente (`npm run build` en ambos frontends) después de cada cambio antes de realizar el commit.
- Al finalizar todas las correcciones, actualiza la tabla de métricas en `AUDIT.md` reflejando las mejoras alcanzadas.