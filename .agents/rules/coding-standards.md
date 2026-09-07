# Rule: Estándares de Código y Estructura en Next.js / TypeScript

## Alcance de Aplicación
* **Patrón de archivo:** Aplicable a todos los archivos dentro de las carpetas `./uis/website/` y `./uis/backend/` (o `./uis/backoffice/`), así como a cualquier módulo en TypeScript.
* **Momento de activación:** Siempre activo cuando el agente escriba, modifique o refactorice componentes de interfaz o lógica frontend.

## Directrices Obligatorias
1. **Tipado Estricto:** Prohibido el uso de `any`. Todos los componentes, props y respuestas de API deben estar fuertemente tipados con interfaces o tipos de TypeScript.
2. **Componentes Reutilizables:** No crear bloques de código monolíticos. Las vistas deben dividirse en componentes atómicos y reutilizables dentro de la carpeta `components/` correspondiente.
3. **Coherencia de Estilos:** Utilizar las clases y directrices visuales acordadas (como Tailwind CSS) manteniendo la identidad corporativa de TrackFlow.
4. **Importaciones Limpias:** Al integrar lógica de negocio previa (Hito 2), importar siempre desde la ruta original del monorepo, evitando duplicar código fuente.