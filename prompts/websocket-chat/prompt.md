# Prompt — Chat por WebSocket (Parte 2 de 2)

Eres un ingeniero senior de backend y frontend en el monorepo TrackFlow. Vas a exponer el **First-line CX agent** (el agente de soporte de `services/agent/`) por **WebSocket**: respuesta token a token, interrupción que aborta de verdad la generación y reconexión que rehidrata la conversación.

**Fuente de verdad:** `memory-bank/history/2026-11-26_websocket-chat.md`. Sigue sus decisiones (D1–D20) al pie de la letra. Si algo del código las contradice, para y pregunta en vez de improvisar.

Antes de nada:
1. Comprueba que estás en la rama `feature/websocket-chat` (`git branch --show-current`). Si no, para.
2. Lee `AGENTS.md`, `uis/backoffice/AGENTS.md`, la primera entrada de `memory-bank/progress.md` y el plan completo.
3. El BRIEFING de la Parte 2 está en la raíz como `trackflow-BRIEFING.es.md`. Es **solo de apoyo**: léelo en la Fase 0, pero nunca lo añadas a git, lo muevas ni lo copies al repo. Lo necesario ya está en el plan.

Forma de trabajar:
- **Una fase cada vez**, empezando por la Fase 0. Al terminar cada fase, responde con la plantilla de resumen del plan y **para**. No sigas hasta que te escriba `OK fase N, continúa`.
- **Un commit por acción** de la tabla, con el mensaje indicado (prefijo convencional + español).
- `git add` con rutas explícitas y `git status` antes de cada commit; nunca `git add .` ni `-A`.
- Git solo en local: nada de `pull`, `fetch`, `merge`, `rebase`, `push`, cambiar de rama ni abrir el PR.
- No leas ni edites ningún `.env*`, el JSON de TinyDB de proveedores ni `node_modules/next/dist/docs`.
- No instales dependencias ni toques `pyproject.toml`, `uv.lock`, `package.json` o `package-lock.json`.
- Puedes ejecutar `pytest` y `npm run typecheck` (después: `git restore uis/backoffice/tsconfig.tsbuildinfo`). `uvicorn`, `npm run dev`, `npm run build` y `npm run start` los lanzo yo: dame el comando y para.
- **No cambies la lógica del agente** (enrutado, tools, RAG, memoria, guardias): solo el canal. Sin `on_token`, `run_agent` y `POST /agent/query` se comportan exactamente como hoy.
- El abort es real (`cancel_event` + `stream.close()` del modelo). **No** uses `interrupt()` de LangGraph para esto.
- Los nombres son los del BRIEFING de la Parte 2 (`ChatSession`: `session_id`, `agent_id = first_line_cx`, `user_id`, `client_id`, `status` `active`/`interrupted`/`closed`, `created_at`; eventos `token_chunk`, `interrupt_requested`, `generation_interrupted`, `generation_completed`, `session_snapshot`, `user_message`). No mezcles nada del contrato SSE/RFP de la Parte 1.

Empieza por la Fase 0.
