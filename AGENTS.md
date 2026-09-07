# AGENTS.md — Protocolo de Operación para Asistentes de IA (TrackFlow)

Este documento establece las normas obligatorias y el flujo de trabajo que cualquier agente de programación (Cursor, Windsurf, Claude Code, etc.) debe seguir estrictamente al interactuar con este monorepo.

---

## 1. Inicialización y Contexto Obligatorio
Antes de iniciar cualquier sesión de trabajo, leer código o escribir modificaciones, el agente **debe leer obligatoriamente** los siguientes archivos del banco de memoria para comprender el negocio y la arquitectura técnica de TrackFlow:
* `memory-bank/projectbrief.md` — Para entender el contexto de negocio, objetivos y problemas logísticos[cite: 1, 2].
* `memory-bank/techContext.md` — Para conocer el stack tecnológico (Next.js, TypeScript), decisiones de arquitectura y estructura del monorepo[cite: 1, 2].
* `memory-bank/progress.md` — Para conocer el estado actual del desarrollo y los siguientes pasos previstos[cite: 1, 2].

---

## 2. Flujo Obligatorio antes de cada Commit
Ningún agente puede realizar un commit ni proponer cambios finales sin cumplir en orden estricto los siguientes **4 pasos de verificación**:
1. **Validación de Tipos y Sintaxis:** Comprobar que no existan errores de TypeScript ni fallos de compilación en los módulos modificados.
2. **Respeto a las Rutas del Monorepo:** Verificar que los nuevos componentes o vistas se alojen en sus carpetas correspondientes (`./uis/website`, `./uis/backoffice`, `/services`) y que no se duplique código de lógica de negocio (debe importarse desde su ubicación original).
3. **Pruebas Locales:** Asegurar que la aplicación compila y arranca correctamente ejecutando las herramientas de prueba o compilación disponibles (`npm run dev`)[cite: 1].
4. **Actualización de Memoria:** Registrar los cambios importantes o avances logrados en el archivo `memory-bank/progress.md` antes de sellar el commit[cite: 1].

---

## 3. Áreas Protegidas (Modificación Restringida)
El agente **tiene estrictamente prohibido** modificar, eliminar o reestructurar los siguientes directorios y archivos sin una confirmación explícita y directa del desarrollador:
* Archivos de configuración global de infraestructura (`infra/`, `scripts/`).
* Credenciales, variables de entorno o tokens de acceso.
* La estructura base de las APIs core definidas en `/services` sin validación previa de arquitectura.

---

## 4. Estándar de Creación y Ejecución de Skills de Agente
Cualquier automatización o **skill** implementada dentro de la carpeta `.agents/skills/` debe cumplir rigurosamente con la siguiente estructura y principios para garantizar su reutilización y calidad:
* **Objetivo Único:** La skill debe resolver una y solo una tarea recurrente del flujo de trabajo de desarrollo o logística[cite: 1].
* **Inputs Definidos:** Deben especificarse claramente los parámetros, archivos de entrada o datos que la skill necesita para operar[cite: 1].
* **Output Esperado:** Debe documentarse de forma explícita qué resultado debe entregar la skill (por ejemplo: un reporte generado, un archivo validado o un componente estructurado)[cite: 1].
* **Criterios de Aceptación Verificables:** Toda skill debe incluir condiciones de éxito binarias o medibles (si no se puede verificar automáticamente o mediante pruebas, la skill no se considera válida)[cite: 1].