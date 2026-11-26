# Prompt — Notificaciones SSE (Parte 1 de 2)

Eres un ingeniero senior de backend y frontend trabajando en el monorepo TrackFlow. Vas a implementar las **notificaciones en tiempo real por SSE** del ticket de RFP.

**Fuente de verdad:** `memory-bank/history/2026-11-26_sse-notifications.md`. Sigue sus decisiones (D1–D14) al pie de la letra; si algo del código las contradice, para y pregunta en vez de improvisar.

Antes de nada:
1. Comprueba que estás en la rama `feature/sse-notifications` (`git branch --show-current`). Si no, para.
2. Lee `AGENTS.md`, `uis/backoffice/AGENTS.md`, la primera entrada de `memory-bank/progress.md` y el plan completo.
3. El BRIEFING está en la raíz como `trackflow-BRIEFING.es.md`. Es **solo de apoyo**: léelo en la Fase 0, pero nunca lo añadas a git, lo muevas ni lo copies al repo. Lo necesario ya está resumido en el plan.

Forma de trabajar:
- **Una fase cada vez**, empezando por la Fase 0. Al terminar cada fase, responde con la plantilla de resumen del plan y **para**. No sigas hasta que te escriba `OK fase N, continúa`.
- **Un commit por acción** de la tabla, con el mensaje indicado (prefijo convencional + español).
- `git add` con rutas explícitas y `git status` antes de cada commit; nunca `git add .` ni `-A`.
- Git solo en local: nada de `pull`, `fetch`, `merge`, `rebase`, `push`, cambiar de rama ni abrir el PR.
- No leas ni edites ningún `.env*`, el JSON de TinyDB de proveedores ni `node_modules/next/dist/docs`.
- No instales dependencias ni toques `pyproject.toml`, `uv.lock`, `package.json` o `package-lock.json`.
- Puedes ejecutar `pytest` y `npm run typecheck` (después: `git restore uis/backoffice/tsconfig.tsbuildinfo`). `uvicorn`, `npm run dev` y `npm run build` los lanzo yo: dame el comando y para.
- Nada de llamadas a modelos o agentes en el código nuevo: esto es una capa de comunicación.
- Los nombres de campos y valores (`ticket_id`, `rfp_id`, `status = "analizando"`, `client_name`, `client_country`, `services_requested`, `created_at`…) son los que ya usa el sistema de RFPs; no inventes otros.

Empieza por la Fase 0.
