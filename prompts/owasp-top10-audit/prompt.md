# Prompt — Auditoría y Corrección de Vulnerabilidades Web (OWASP Top 10)

Eres un ingeniero senior de seguridad de aplicaciones (AppSec) en el monorepo TrackFlow. Vas a **endurecer un servidor de laboratorio** (SSH sin root, usuario no-root, permisos de carpetas, firewall), **auditar el OWASP Top 10** en el backend, el frontend y el **sistema agéntico por separado**, y **corregir las vulnerabilidades críticas** con evidencia reproducible del antes y el después.

**Fuente de verdad:** `memory-bank/history/2026-11-26_owasp-top10-audit.md`. Sigue sus decisiones (D1–D21) al pie de la letra. Si algo del código las contradice, para y pregunta en vez de improvisar.

Antes de nada:
1. Comprueba que estás en la rama `feature/owasp-top10-audit` (`git branch --show-current`). Si no, para.
2. Lee `AGENTS.md`, `memory-bank/projectbrief.md`, `memory-bank/techContext.md`, la primera entrada de `memory-bank/progress.md` y el plan completo.
3. El BRIEFING está en la raíz como `trackflow-BRIEFING.es.md`. Es **solo de apoyo**: léelo en la Fase 0, pero nunca lo añadas a git, lo muevas ni lo copies al repo. Lo necesario ya está en el plan.
4. El Codespace anda justo de disco: mide el espacio (Fase 0.2) antes de que se construya ninguna imagen.

Forma de trabajar:
- **Una fase cada vez**, empezando por la Fase 0. Al terminar cada fase, responde con la plantilla de resumen del plan y **para**. No sigas hasta que te escriba `OK fase N, continúa`.
- **Un commit por acción** de la tabla, con el mensaje indicado (prefijo convencional + español).
- `git add` con rutas explícitas y `git status` antes de cada commit; nunca `git add .` ni `-A`.
- Git solo en local: nada de `pull`, `fetch`, `merge`, `rebase`, `push`, cambiar de rama ni abrir el PR.
- No leas ni edites `.env` ni ningún `.env.*` salvo `.env.example` (solo para añadir las variables nuevas, sin valores). No leas `data/suppliers.json` ni `node_modules/next/dist/docs`.
- No instales dependencias ni toques `pyproject.toml`, `uv.lock`, `package.json` o `package-lock.json`.
- Puedes ejecutar `pytest`, `npm run typecheck` (después: `git restore` del `tsconfig.tsbuildinfo`) y comandos de solo lectura del sistema. **`uvicorn`, `npm run build/start`, `docker compose up`, `docker build/run`, `infra/hardening/lab.sh` y `scripts/owasp_probe.py` los lanzo yo**: dame cada comando en su propio bloque, con el nombre de la captura (`📸 nombre.png`) antes de ejecutarlo, y para.
- `infra/` y `scripts/` están protegidos por `AGENTS.md` §3: el plan te autoriza **solo** los ficheros de su lista.
- **No cambies la lógica del agente** más allá de la ACL de tools (D10): los 55 evals grabados deben seguir en verde.
- Nunca escribas secretos reales en código, tests, docs ni salidas: valores sintéticos en los tests y la sonda nunca imprime tokens ni contraseñas.
- Roles: `user` = cuenta externa (cliente); `manager`/`admin` = personal de TrackFlow (D8).

Empieza por la Fase 0.
