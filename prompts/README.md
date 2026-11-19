# Prompts de agentes de IA

Índice de los prompts usados en cada proyecto del monorepo TrackFlow.
Cada carpeta contiene `prompt.md` (instrucciones para el agente) y `progress.md` (registro de avance).

| Proyecto | Carpeta | Rama | Estado | PR |
|----------|---------|------|--------|----|
| Auditoría de Serialización del Backend | `serialization-audit/` | `feature/serialization-audit` | En curso | — |
| Optimización de rendimiento: Caching | `caching-optimisation/` | `feature/caching-optimisation` | Mergeado | #15 |
| Diseño del Plan de Telemetría | `telemetry-design/` | `feature/telemetry-design-plan` | Mergeado | #17 |
| Captura de telemetría en el frontend | `telemetry-frontend-capture/` | `feature/telemetry-frontend-capture` | Mergeado | #18 |
| Almacenamiento de telemetría | `telemetry-storage/` | `feature/telemetry-storage` | PR abierto | #19 |
| Reporte técnico de telemetría | `telemetry-report/` | `feature/telemetry-report` | En curso | — |

Convención desde el proyecto de caching: el plan y su registro de avance se
guardan juntos en `memory-bank/history/AAAA-MM-DD_<proyecto>.md`;
`memory-bank/progress.md` mantiene el registro global y
`prompts/<proyecto>/prompt.md` contiene el prompt de arranque. Los proyectos
anteriores conservan su estructura.

## Cómo empezar un proyecto nuevo
1. Copia la plantilla: `cp -r prompts/_template prompts/<nombre-proyecto>`
2. Rellena los campos entre [CORCHETES] de `prompt.md` con lo que pide la rúbrica.
3. Añade una fila a la tabla de arriba.
