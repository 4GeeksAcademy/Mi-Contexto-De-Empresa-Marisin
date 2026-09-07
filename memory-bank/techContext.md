# Tech Context: Arquitectura y Stack Tecnológico

## Stack Tecnológico Principal
* **Frontend / Interfaces:** Next.js con TypeScript, organizadas en monorepo bajo la carpeta `/uis` (incluyendo `./uis/website` y `./uis/backoffice`).
* **Lógica de Negocio y Servicios:** Módulos desarrollados en TypeScript e integrados desde las carpetas globales del monorepo hacia las interfaces y servicios (`/services`).
* **Control de Versiones y Agentes:** Git, GitHub, configuraciones de gobernanza para asistentes de IA en la carpeta `.agents/` y banco de memoria en `memory-bank/`.

## Decisiones de Arquitectura
* **Monorepo Unificado:** Todo el código de la empresa (web pública, backoffice, lógica de negocio y futuros agentes) reside en un único repositorio estructurado por capas.
* **Aislamiento de Aplicaciones:** Las interfaces de usuario de Next.js se mantienen separadas por dominios (`website` para clientes corporativos/público y `backoffice` para la operación interna).
* **Reutilización estricta:** La lógica de negocio previa (Hito 2) no se duplica; se importa de forma directa en el backoffice para garantizar una única fuente de verdad.

## Restricciones Técnicas
* Soporte multi-entorno y transfronterizo (necesidad de contemplar operaciones adaptadas a normativas y flujos de EE. UU. y España).
* Los asistentes de IA configurados en el repositorio deben ceñirse estrictamente a las reglas de desarrollo y flujos de commit definidos en `AGENTS.md`.