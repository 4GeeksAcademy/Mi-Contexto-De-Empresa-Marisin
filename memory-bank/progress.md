# Progress: Estado Actual y Próximos Pasos

## Estado Actual del Desarrollo
* **Hitos Completados:** Desarrollo de la web pública corporativa, módulos lógicos iniciales en TypeScript y primeros componentes de asistencia.
* **Fase Actual (Hito 4):** Establecimiento de la infraestructura de ingeniería impulsada por IA, configuración del banco de memoria de TrackFlow, definición de `AGENTS.md`, reglas en `.agents/`, y estructuración del monorepo con Next.js (`./uis/website` y `./uis/backoffice`).
* **Actualización 2026-08-03:** Se implementó la aplicación pública en `./uis/website` con Next.js App Router + TypeScript + Tailwind CSS, landing corporativa modular, formulario B2B con validaciones estrictas y marcado SEO `Organization` con Schema.org.
* **Actualización 2026-08-03 (backoffice):** Se implementó `./uis/backoffice` como aplicación independiente con layout corporativo interno, dashboard de entrada y paneles interactivos que reutilizan la lógica de negocio existente de `src/utils`/`src/types` (operaciones) y `uis/talent-pipeline-tracker/services/api.ts` (talento), sin duplicar código.
* **Actualización 2026-10-21 (inventario):** Se implementó el router de inventario con stock calculado por almacén, validación de salidas antes de persistir, trazabilidad de TinyDB y respuestas enriquecidas con producto y usuario. Smoke test local, registro OpenAPI y consulta real a Supabase verificados.
* **Actualización 2026-10-21 (semilla de inventario):** `services/api/seed.py` siembra 2 productos y 8 movimientos de forma transaccional e idempotente. La verificación contra Supabase Transaction Pooler confirmó `GET /inventory/products` con HTTP 200 y stocks 173 y 81. Para la prueba se eliminó del entorno del proceso una `DATABASE_URL` heredada que apuntaba al endpoint directo, permitiendo cargar la URI correcta desde `.env`.
* **Actualización 2026-10-29 (arranque de la API):** Se restauraron en `services/api/models.py` los contratos compartidos de proveedores, usuarios, perfiles y autenticación, conservando los modelos nuevos de inventario. El router de autenticación vuelve a importar desde `models`. Verificados importación de la aplicación, generación de OpenAPI con 18 rutas y `GET /docs` con HTTP 200 al ejecutar `python -m uvicorn services.api.main:app --reload`.

* **Verificación 2026-10-29 (autenticación TinyDB):** Auth utiliza contratos definidos en `schemas.py`; la verificación segura acepta `hashed_password` o, en su ausencia, `password_hash`, rechazando hashes inválidos sin errores 500. Los helpers reconstruyen el ID desde `doc_id` y la comprobación de usuario activo es consistente entre login y JWT. Verificados 11 escenarios HTTP con TinyDB en memoria, sintaxis y Swagger con HTTP 200. Sin cambios en `models.py` ni en la lógica de inventario.

## Próximos Pasos Previstos

* Finalizar la integración visual del módulo de lógica de negocio (Hito 2) dentro del backoffice operativo de TrackFlow.
* Implementar una skill de agente ejecutable y verificable en `.agents/skills/` orientada a tareas recurrentes del monorepo.
* Ejecutar el flujo de entrega, validación de compilación (`npm run dev`) y apertura de la Pull Request hacia la rama `main`.