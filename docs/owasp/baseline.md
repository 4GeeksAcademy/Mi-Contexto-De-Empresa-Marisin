# Línea base de seguridad (antes de la auditoría OWASP)

Foto del estado **antes de corregir nada** (rama `feature/owasp-top10-audit`, commit
de partida `3a67f12`, recogida el 2026-11-26). Sirve de «antes» para cada hallazgo
del informe `docs/owasp/OWASP_TOP10_AUDIT.md`. Ningún valor secreto aparece aquí.

---

## (a) Codespace (entorno de desarrollo)

El Codespace es el entorno de desarrollo que gestiona GitHub: solo se entra con la
cuenta de GitHub. No es el servidor de producción, que se simula en el laboratorio
de `infra/hardening/` (D1). Aquí solo se documenta y **no se modifica**.

### Usuario y privilegios

```text
$ id
uid=1000(vscode) gid=1000(vscode) groups=1000(vscode),800(docker),996(pipx),997(python),998(nvm),1001(ssh)
$ whoami
vscode
$ sudo -n true && echo "sudo sin contraseña"
sudo sin contraseña
```

- El usuario de trabajo **no es root** (`vscode`, uid 1000).
- Tiene **sudo sin contraseña** y pertenece al grupo `docker`, que equivale a root en
  el host de Docker. Es lo normal en un devcontainer, pero en un servidor real sería
  inaceptable (en el laboratorio, `trackflow-ops` usa sudo **con** contraseña).

### SSH

```text
$ grep -n 'PermitRootLogin\|PasswordAuthentication\|^Port\|KbdInteractive' /etc/ssh/sshd_config
23:Port 2222
42:PermitRootLogin yes
66:#PasswordAuthentication yes
71:KbdInteractiveAuthentication no
$ ls /etc/ssh/sshd_config.d/
(vacío)
```

- El feature `sshd` del devcontainer arranca `sshd` en el **puerto 2222**, con
  `PermitRootLogin yes`. `PasswordAuthentication` está comentado, así que vale el
  valor por defecto de OpenSSH (`yes`).
- No hay ningún drop-in en `sshd_config.d/`.
- Mitigación del entorno: el 2222 no se reenvía (`forwardPorts` no lo incluye) y
  Codespaces solo es accesible con la cuenta de GitHub (`gh codespace ssh`).

### Puertos en escucha

```text
$ ss -tlnp   (resumen)
0.0.0.0:2000   y [::]:2000   agente de Codespaces
0.0.0.0:2222   y [::]:2222   sshd (feature sshd del devcontainer)
127.0.0.53:53                resolvedor DNS local
127.0.0.1:<efímeros>         VS Code Server, extensiones y Claude Code (solo loopback)
```

En el momento de la captura no estaban arrancados ni la API (8000), ni los
frontends (3000–3002), ni Qdrant, Redis o Flower.

### Contenedores

```text
$ docker ps --format '{{.Names}}\t{{.Ports}}'
nostalgic_nash
```

No había ningún contenedor de la pila con puertos publicados. Al arrancarlos,
`docker-compose.yml` los publica en `0.0.0.0` (ver C5). La captura con la pila
arrancada la hace Marisin (📸 `docker-ports-antes.png`, abajo).

### `.devcontainer/devcontainer.json`

| Clave | Valor | Línea |
|-------|-------|-------|
| `image` | `mcr.microsoft.com/devcontainers/base:ubuntu-24.04` | `:3` |
| feature `sshd` | `ghcr.io/devcontainers/features/sshd:1` | `:14` |
| feature `docker-outside-of-docker` | usa el Docker del host | `:12` |
| `forwardPorts` | `3000, 3001, 3002, 8000` | `:44` |
| `remoteUser` | `vscode` (no root) | `:45` |

---

## (b) Aplicación (API FastAPI)

### Inventario de rutas y su protección actual

Hay **53 operaciones HTTP** (`app.openapi()["paths"]`) más el WebSocket del chat
(`/agent/chat/sessions/{session_id}/ws`, que exige el JWT antes de cualquier frame). La
columna «Protección» viene del árbol de dependencias de cada ruta (¿depende de
`get_current_user`?) y de los controles de rol que se hacen dentro de la función.

**Públicas, sin token (13):**

| Método | Ruta | ¿Debería serlo? |
|--------|------|-----------------|
| POST | `/auth/login` | Sí |
| POST | `/auth/forgot-password` | Sí |
| POST | `/auth/reset-password` | Sí |
| POST | `/users` | Sí (registro público → rol `user`) |
| POST | `/telemetry/events` | Sí (ingesta del frontend) |
| GET | `/api/incidents` | **No** (C1) |
| POST | `/api/incidents` | **No** (C1) |
| GET | `/api/incidents/summary` | **No** (C1) |
| GET | `/api/incidents/{incident_id}` | **No** (C1) |
| PATCH | `/api/incidents/{incident_id}/status` | **No** (C1) |
| GET | `/inventory/products` | **No** (C4) |
| GET | `/inventory/products/{product_id}` | **No** (C4) |
| GET | `/inventory/orders` | **No** (C4) |

**Con rol (solo `admin`/`manager`) (6):**

| Método | Ruta | Control |
|--------|------|---------|
| GET | `/agent/traces/{run_id}` | `TRACE_ROLES` (`services/agent/router.py:55,113`) |
| GET | `/agent/memory` | `require_trace_role` (`:124`) |
| GET | `/agent/memory/audit` | `require_trace_role` (`:138`) |
| GET | `/agent/guardrails/summary` | `require_trace_role` (`:152`) |
| POST | `/reporting/pipeline-runs` | `TRIGGER_ROLES` (`services/reporting/router.py:47,122`) |
| GET | `/profiles/{profile_id}` | el propio usuario o `admin` (`routes/profiles.py:40`) |

**Con control de propiedad (dueño o `admin`) (2):** `PUT /users/{user_id}` y
`DELETE /users/{user_id}` (`routes/users.py:49,69`; cambiar el rol solo lo hace un
admin, `:51-52`).

**Cualquier usuario autenticado, sin comprobar rol (32).** Cualquiera que se
registre con `POST /users` recibe el rol `user` y puede llamarlas:

| Grupo | Rutas | ¿Correcto? |
|-------|-------|------------|
| Cuenta propia | `GET /auth/me`, `POST /auth/change-password`, `GET/PUT /profiles/me` | Sí |
| Agente / chat | `POST /agent/query`, `POST /agent/chat/sessions` | Sí (los clientes usan el chat) |
| Usuarios | `GET /users`, `GET /users/{user_id}` | **No**: emails y roles de todos (C4) |
| Proveedores | `GET/POST /suppliers`, `GET/DELETE /suppliers/{id}`, `PATCH /suppliers/{id}/rate`, `PATCH /suppliers/{id}/status` | **No**: tarifas y escritura (C4) |
| Inventario (escritura) | `POST /inventory/products`, `POST /inventory/orders/inbound`, `POST /inventory/orders/outbound`, `PATCH /inventory/products/{id}/stock` (siempre 405) | **No** (C4) |
| RFPs B2B | `GET/POST /rfp/tickets`, `GET /rfp/tickets/{id}`, `/drafts`, `/approvals`, `/approvals/{department_id}`, `/trace`, `/document` | **No**: RFPs confidenciales (C4) |
| Reporting | `GET /reporting/pipeline-runs/latest`, `GET /reporting/weekly-warehouse-client-performance` | **No**: KPIs por almacén y cliente B2B (C4) |
| Conocimiento | `POST /knowledge/query` | **No** (C4) |
| Tiempo real | `GET /realtime/events` | **No**: stream de RFPs (C4) |
| Tareas | `GET /tasks/{task_id}` | **No** (C4) |
| Telemetría | `GET /telemetry/report` | **No** (C4) |

Total: 13 + 6 + 2 + 32 = **53**.

### Hallazgos críticos y altos (con fichero:línea)

| Id | OWASP | Carril | Hallazgo | Evidencia |
|----|-------|--------|----------|-----------|
| C1 | A01 | Backend | Las 5 rutas de `/api/incidents` no exigen autenticación. El MCP aplica los scopes `incidents:read`/`incidents:write`, pero la API que hay detrás está abierta. | `services/api/routes/incidents.py:28` (router sin dependencias), `:31,38,49,66,71` |
| C2 | A01 | Agente | `lookup_ticket` y `lookup_inventory` llaman a las tools MCP para **cualquier rol**: un cliente (`user`) desde el chat lista incidencias internas y el stock de todas las marcas B2B (con `client_name`). | `services/agent/nodes.py:216-229`, `services/agent/answers.py:79` |
| C3 | A07 | Backend | En cada arranque se crea, si no existe, el admin `admin@test.com` con una contraseña escrita en el código. | `services/api/database.py:57-66`, `services/api/main.py:142`, `scripts/perf/bench_endpoints.py:17-18` |
| C4 | A01 | Backend | El registro público da el rol `user`, y con ese token se leen usuarios, proveedores (y se escriben), RFPs, KPIs B2B, conocimiento, el stream de tiempo real, tareas, telemetría e inventario. | `routes/users.py:19-33`, `routes/suppliers.py:18-113`, `services/rfp/router.py:123-314`, `services/reporting/router.py:66-90`, `services/knowledge/router.py:32`, `services/realtime/router.py:120`, `routes/tasks.py:84`, `routes/telemetry.py:87`, `routes/inventory.py:71,117,208` |
| C5 | A05 | Infra | Qdrant (6333, sin API key), Redis (6379, sin contraseña) y Flower (5555, sin auth: ve los argumentos de las tareas y puede revocarlas) se publican en `0.0.0.0`; también 3000–3002 y 8000. | `docker-compose.yml:8-10,30,57,70,86` |
| C6 | A05 | Infra/Agente | La API (y con ella el agente) y el worker de Celery, que usan la misma imagen, corren **como root** y con `--reload`; los frontends también corren como root. | `services/Dockerfile:1-14` (sin `USER`, `--reload` en `:14`), `uis/Dockerfile:1-14` (sin `USER`) |
| H1 | A07/A09 | Backend | Login y forgot-password sin límite de intentos y sin registrar los fallos. | `services/api/routes/auth.py:39-51`, `:63-88` |
| H2 | A05 | Backend | La API no envía cabeceras de seguridad (`nosniff`, `X-Frame-Options`, `Referrer-Policy`…). | `services/api/main.py:73-105` (solo CORS y el middleware de tiempos) |

Otros hallazgos (medios/bajos) que se documentan en el informe sin corregir:

- `main.py:81-82`: CORS `allow_origin_regex=r"https://.*\.app\.github\.dev"` acepta cualquier Codespace (riesgo bajo: `allow_credentials=False` y el token va en una cabecera).
- `main.py:104-105`: el log de tiempos imprime la query string completa.
- `services/api/auth.py`: un segundo sistema de tokens que no se usa en producción (solo `tests/test_auth.py`).
- `services/api/security.py:30-32`: `JWT_SECRET` sin comprobar su longitud; HS256, 60 min, sin revocación.
- `mcps/trackflow_mcp/config.py:50`: `MCP_ALLOWED_ORIGINS` vale `*` por defecto.
- `uis/backoffice/src/lib/api.ts:20`: el JWT se guarda en `localStorage`.
- Ningún `next.config.ts` (`uis/{website,backoffice,application}`) define cabeceras de seguridad ni CSP.

Controles que ya estaban bien (✔): contraseñas con bcrypt (`security.py:13`); tokens de reset guardados como SHA-256 y de un solo uso (`routes/auth.py:70-80,96-116`); todo el acceso a datos pasa por el ORM (sin SQL con f-strings); los 500 no devuelven la traza (`main.py:121-137`); pedidos del agente solo para su dueño (`harness/authorization.py:100`); saneado de tools y RAG (`harness/isolation.py:42-75`); el agente solo pide scopes de lectura (`mcp_client.py:36`); el chat WS exige el JWT y oculta el token en los logs (`chat/logging_filters.py:20`).

### Componentes del BRIEFING (sección 3) que no existen en el fork

Búsqueda en el código (`*.py`, `*.ts`, `*.tsx`, `*.yml`, `*.example`; sin
`node_modules`, `.next`, `.venv`, `docs`, `memory-bank` ni `prompts`):

| Componente | Patrón buscado (`grep -rni`) | Resultado |
|------------|------------------------------|-----------|
| Motor de selección de carrier | `carrier_selection\|select_carrier\|CarrierEngine\|carrier_engine` | Sin coincidencias |
| Motor de aprobación de devoluciones | `approve_return\|return_approval\|ReturnApproval\|returns_engine` | Sin coincidencias |
| API de tracking | `tracking_api\|/tracking\|TrackingAPI` | Solo comentarios de `services/agent/harness/authorization.py:46,62` y `harness/__init__.py:9` (las referencias de pedido del directorio de demostración `data/agent/shipments.json`) |
| Portales B2B | `b2b_portal\|/portal\|BrandPortal` | Sin coincidencias |
| Credenciales de couriers | `COURIER_\|CARRIER_API_KEY\|UPS_\|FEDEX_\|DHL_` | Sin coincidencias en el código (un falso positivo en un nombre de test) |
| Secretos de webhook | `WEBHOOK_SECRET\|webhook_secret` | Sin coincidencias |

---

## (c) Evidencias del «antes» (las ejecuta Marisin)

| Captura | Comando | Qué debe verse | Resultado |
|---------|---------|----------------|-----------|
| 📸 [`owasp-probe-antes.png`](evidence/owasp-probe-antes.png) · [`.txt`](evidence/owasp-probe-antes.txt) | `python scripts/owasp_probe.py` (con la API en marcha) | FAIL en P1–P4 y P6–P8; PASS en P5 | ✅ Como se esperaba: **1/8 PASS** (solo P5). Sin token, `GET /api/incidents` → 200 y la clave de servicio falsa → 200; login con la contraseña por defecto del admin → 200; inventario sin token → 200; las 6 rutas internas con token `user` → 200; el agente ejecutó `lookup_inventory` para un `user` (`status=unavailable`: el MCP no estaba arrancado); ninguna cabecera de seguridad; 6 logins fallidos → 6 × 401, sin límite |
| 📸 [`docker-ports-antes.png`](evidence/docker-ports-antes.png) · [`.txt`](evidence/docker-ports-antes.txt) | `docker ps --format '{{.Names}}\t{{.Ports}}'` (con Qdrant y Redis arrancados) | `0.0.0.0:6333`, `0.0.0.0:6379`… | ✅ `0.0.0.0:6333->6333/tcp, [::]:6333->6333/tcp` y `0.0.0.0:6379->6379/tcp, [::]:6379->6379/tcp` |
| 📸 [`lab-01-audit-antes.png`](evidence/lab-01-audit-antes.png) · [`.txt`](evidence/lab-01-audit-antes.txt) | `infra/hardening/lab.sh audit` | FAIL en root SSH, password auth, usuarios, permisos y ufw | ✅ **PASS=5 FAIL=23**: `PermitRootLogin yes`, `PasswordAuthentication yes`, root con clave autorizada, sin `trackflow-ops` ni `trackflow`, las 5 rutas de `/srv/trackflow` en `777` (7 rutas escribibles por cualquiera), ufw `inactive` |
| 📸 [`lab-02-scan-antes.png`](evidence/lab-02-scan-antes.png) · [`.txt`](evidence/lab-02-scan-antes.txt) | `infra/hardening/lab.sh scan` | 11 puertos abiertos | ✅ **11 de 11** abiertos (22 80 443 3000 3001 3002 5555 6333 6379 8000 8001) |
| 📸 [`lab-03-ssh-antes.png`](evidence/lab-03-ssh-antes.png) · [`.txt`](evidence/lab-03-ssh-antes.txt) | `infra/hardening/lab.sh ssh-test` | root entra por SSH | ✅ root **ENTRA** (`uid=0(root)`); `trackflow-ops` no existe todavía |

Las capturas se guardan en `docs/owasp/evidence/`. El «después» de cada una está en [`verification.md`](verification.md) y en el [informe](OWASP_TOP10_AUDIT.md).
