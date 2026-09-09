# Progress: Estado Actual y Próximos Pasos

## Estado Actual del Desarrollo
* **Hitos Completados:** Desarrollo de la web pública corporativa, módulos lógicos iniciales en TypeScript y primeros componentes de asistencia.
* **Fase Actual (Hito 4):** Establecimiento de la infraestructura de ingeniería impulsada por IA, configuración del banco de memoria de TrackFlow, definición de `AGENTS.md`, reglas en `.agents/`, y estructuración del monorepo con Next.js (`./uis/website` y `./uis/backoffice`).
* **Actualización 2026-08-03:** Se implementó la aplicación pública en `./uis/website` con Next.js App Router + TypeScript + Tailwind CSS, landing corporativa modular, formulario B2B con validaciones estrictas y marcado SEO `Organization` con Schema.org.
* **Actualización 2026-08-03 (backoffice):** Se implementó `./uis/backoffice` como aplicación independiente con layout corporativo interno, dashboard de entrada y paneles interactivos que reutilizan la lógica de negocio existente de `src/utils`/`src/types` (operaciones) y `uis/talent-pipeline-tracker/services/api.ts` (talento), sin duplicar código.

## Próximos Pasos Previstos
* Finalizar la integración visual del módulo de lógica de negocio (Hito 2) dentro del backoffice operativo de TrackFlow.
* Implementar una skill de agente ejecutable y verificable en `.agents/skills/` orientada a tareas recurrentes del monorepo.
* Ejecutar el flujo de entrega, validación de compilación (`npm run dev`) y apertura de la Pull Request hacia la rama `main`.

## Actualización 2026-09-09 (Gestor de Incidencias)
* Fase 1 completada: contrato compartido de validación CSV en `packages/shared/incident_validation.py` y tipos TypeScript de incidencias en `packages/shared/types/index.ts`.
* Fase 2 completada: modelo, persistencia, servicio y endpoints de incidencias en `services/api/`, con validaciones, transiciones, resumen y errores HTTP sin stack traces.
* Fase 3 completada: formulario, listado filtrable con rollback optimista y resumen en `uis/application/` bajo `app/incidents`, `components/incidents` y `lib/incidents`.
* Verificado: seed idempotente con CSV temporal, contrato HTTP de la API, ESLint/TypeScript focalizado y `npm run build` del backoffice.
* Ajuste 2026-09-09: los enums de incidencias se comparten directamente entre `packages/shared/incident_validation.py` y `services/api/models.py`; el resumen visualiza total, estados, categorías, orígenes y sedes.
* La tabla temporal `incidents` se elimina del JSON de proveedores tras las pruebas; el seed histórico real y las pruebas persistentes siguen pendientes por no estar incluido el CSV en el repositorio.