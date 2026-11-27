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
| Reporte técnico de telemetría | `telemetry-report/` | `feature/telemetry-report` | PR abierto | #20 |
| Diseño del Pipeline de Desempeño de Negocio (1/3) | `pipeline-design/` | `feature/pipeline-design` | PR abierto | #21 |
| Pipeline de Desempeño de Negocio Resiliente (2/3) | `pipeline-implementation/` | `feature/pipeline-implementation` | PR abierto | #22 |
| Subflows, tests y dashboard del pipeline (3/3) | `pipeline-subflows/` | `feature/pipeline-subflows` | PR abierto | #23 |
| Procesos en segundo plano: script nocturno de telemetría | `nightly-export/` | `feature/nightly-export` | PR abierto | #24 |
| Colas de mensajes y tareas asíncronas (Redis + Celery) | `async-tasks/` | `feature/async-tasks` | PR abierto | #25 |
| Sistemas en tiempo real: notificaciones SSE (Parte 1/2) | `sse-notifications/` | `feature/sse-notifications` | PR abierto | #37 |
| Sistemas en tiempo real: chat por WebSocket (Parte 2/2) | `websocket-chat/` | `feature/websocket-chat` | PR abierto | #38 |
| Auditoría y corrección de vulnerabilidades web (OWASP Top 10) | `owasp-top10-audit/` | `feature/owasp-top10-audit` | PR abierto | #39 |

Convención desde el proyecto de caching: el plan y su registro de avance se
guardan juntos en `memory-bank/history/AAAA-MM-DD_<proyecto>.md`;
`memory-bank/progress.md` mantiene el registro global y
`prompts/<proyecto>/prompt.md` contiene el prompt de arranque. Los proyectos
anteriores conservan su estructura.

## Cómo empezar un proyecto nuevo
1. Copia la plantilla: `cp -r prompts/_template prompts/<nombre-proyecto>`
2. Rellena los campos entre [CORCHETES] de `prompt.md` con lo que pide la rúbrica.
3. Añade una fila a la tabla de arriba.
