# Endurecimiento del servidor de TrackFlow

Línea base de seguridad del servidor que publica la API y los frontends de TrackFlow: **SSH sin root, usuario de operaciones sin root, permisos de carpetas explícitos y firewall con solo los puertos necesarios**. Forma parte de la [auditoría OWASP Top 10](OWASP_TOP10_AUDIT.md) (carril Infraestructura).

- **Dónde se prueba:** un servidor de laboratorio en Docker que simula el VPS de producción (Ubuntu 24.04), arrancado en una configuración por defecto **insegura a propósito** y endurecido con el script del repo. El Codespace es el entorno de desarrollo gestionado por GitHub: se documenta en la [línea base](baseline.md#a-codespace-entorno-de-desarrollo), pero no se modifica.
- **Ficheros:** [`infra/hardening/`](../../infra/hardening/) (`harden.sh`, `audit.sh`, `scan_ports.sh`, `lab.sh`, drop-in de SSH e imagen del laboratorio). Uso paso a paso en su [README](../../infra/hardening/README.md).
- **Resultado:** `audit.sh` pasa de **5 PASS / 23 FAIL** a **28 PASS / 0 FAIL**; los puertos abiertos pasan de **11 a 3** (22, 80, 443); root deja de entrar por SSH y `trackflow-ops` entra.

---

## 1. Usuarios

| Cuenta | Para qué | Shell | sudo | SSH |
|--------|----------|-------|------|-----|
| `root` | Administración del sistema | — | — | **Denegado** (`PermitRootLogin no`, claves autorizadas eliminadas) |
| `trackflow-ops` | Personas de operaciones: despliegan y revisan logs | `/bin/bash` | Grupo `sudo`, **con contraseña** | Solo con clave pública |
| `trackflow` | Cuenta de servicio, dueña de los procesos de la API y del worker | `/usr/sbin/nologin` | No | No (no está en `AllowUsers`) |

**Por qué así:**
- **Nadie entra como root.** Las operaciones privilegiadas se hacen con `sudo` desde una cuenta personal, que deja rastro y exige la contraseña. Si alguien roba la clave SSH, sigue sin poder hacer de root.
- **La cuenta del servicio no puede iniciar sesión** ni elevar privilegios. Si un atacante consigue ejecutar código en la API (o en el agente, que vive en ella), queda encerrado en una cuenta sin shell, sin sudo y sin acceso de escritura al código.
- **`trackflow-ops` no está en el grupo `trackflow`**, así que no lee los secretos del servicio (sección 3).

Los contenedores de la pila siguen el mismo principio: la API, el agente y el worker corren como `trackflow` (uid 10001) y los frontends como `node` (`services/Dockerfile`, `uis/Dockerfile`; hallazgo C6 del informe).

## 2. SSH

Drop-in [`10-trackflow-hardening.conf`](../../infra/hardening/sshd_config.d/10-trackflow-hardening.conf), instalado en `/etc/ssh/sshd_config.d/`. Ubuntu 24.04 lee ese directorio al principio de `sshd_config` y en `sshd` gana el primer valor, así que el drop-in manda sobre el fichero principal. `harden.sh` lo valida con `sshd -t` **antes** de recargar, para no dejar el servidor sin acceso por un error de sintaxis.

| Opción | Valor | Motivo |
|--------|-------|--------|
| `PermitRootLogin` | `no` | Sin acceso directo como root |
| `PasswordAuthentication`, `KbdInteractiveAuthentication` | `no` | Sin contraseñas que adivinar por fuerza bruta |
| `PubkeyAuthentication`, `AuthenticationMethods` | `yes`, `publickey` | Solo clave pública |
| `AllowUsers` | `trackflow-ops` | Ninguna otra cuenta puede entrar, aunque tenga clave |
| `MaxAuthTries`, `LoginGraceTime` | `3`, `30` | Menos margen por conexión (ufw limita además el número de conexiones) |
| `X11Forwarding`, `AllowTcpForwarding` | `no` | SSH es para operar, no para hacer túneles hacia Redis o Qdrant |
| `ClientAliveInterval`, `ClientAliveCountMax` | `300`, `2` | Cierra las sesiones abandonadas |

La comprobación se hace sobre la **configuración efectiva** (`sshd -T`), no sobre el fichero.

## 3. Permisos de carpetas

| Ruta | Modo | Dueño:grupo | Quién hace qué |
|------|------|-------------|----------------|
| `/srv/trackflow` | `755` | `root:root` | Raíz; nadie más que root la cambia |
| `app/` (código) | `750`, ficheros `640` | `trackflow-ops:trackflow` | Ops despliega; **el servicio solo lee** (no puede modificar su propio código); otros, nada |
| `logs/` | `2750` (setgid) | `trackflow:trackflow-ops` | Escribe el servicio; ops lee; los ficheros nuevos heredan el grupo `trackflow-ops` |
| `config/` | `750` | `root:trackflow` | Configuración sensible |
| `config/.env` | `640` | `root:trackflow` | Solo root la cambia (con `sudo`); el servicio la lee; **ops no lee los secretos** |

Además, el servicio corre con `UMask=0027` (drop-in de systemd `trackflow-api.service.d/10-hardening.conf`), así que nada de lo que cree es legible por «otros».

Antes del endurecimiento, las cinco rutas tenían `777 root:root` y había 7 rutas escribibles por cualquiera (`lab-01-audit-antes`).

## 4. Firewall

`ufw` con `default deny incoming`, `default allow outgoing` y tres reglas de entrada:

| Puerto | Servicio | Estado | Por qué |
|--------|----------|--------|---------|
| 22/tcp | SSH | **Abierto** con `limit` | Solo para ops; `limit` bloquea una IP que abre ≥ 6 conexiones en 30 s |
| 80/tcp | HTTP | **Abierto** | Solo para redirigir a HTTPS (y para el reto HTTP-01 de Let's Encrypt) |
| 443/tcp | HTTPS | **Abierto** | API y frontends detrás del proxy inverso, que termina TLS. El MCP se publicaría como ruta `/mcp` |
| 3000–3002 | Frontends Next.js | Cerrado | Se sirven por el 443 a través del proxy |
| 8000 | API FastAPI | Cerrado | Ídem |
| 8001 | Servidor MCP | Cerrado | Ídem (`/mcp` del 443) |
| 5555 | Flower | Cerrado | Ve los argumentos de las tareas y puede revocarlas: nunca público. Además, en `docker-compose.yml` solo arranca con `--profile dev` y con `FLOWER_BASIC_AUTH` |
| 6333 | Qdrant | Cerrado | Sin API key; solo lo usa la API desde la red interna |
| 6379 | Redis | Cerrado | Sin contraseña; broker de Celery y memoria del agente, solo red interna |

Es lo que pide el BRIEFING: «Público: HTTPS API + frontend; SSH solo ops». Hay una segunda capa independiente: `docker-compose.yml` publica todos los puertos solo en `127.0.0.1` (`${TRACKFLOW_BIND_ADDR:-127.0.0.1}`, hallazgo C5), así que aunque el firewall se desactivara, Redis, Qdrant y Flower seguirían sin ser accesibles desde fuera.

## 5. Resultados del laboratorio

Todo con el mismo comando antes y después (`infra/hardening/lab.sh <subcomando>`). Salidas completas en `evidence/` (`.txt` y captura `.png`).

| Paso | Antes | Después | Evidencia |
|------|-------|---------|-----------|
| Espacio en disco antes de construir | 21 GB libres (33 % usado) | — | `lab-00-espacio` |
| `audit` | **PASS=5 FAIL=23**: `PermitRootLogin yes`, `PasswordAuthentication yes`, sin `trackflow-ops` ni `trackflow`, todo en `777`, ufw `inactive` | **PASS=28 FAIL=0** | [`lab-01-audit-antes.txt`](evidence/lab-01-audit-antes.txt) → [`lab-05-audit-despues.txt`](evidence/lab-05-audit-despues.txt) |
| `scan` (desde otro contenedor de la red) | **11 de 11** abiertos | **3 de 11**: 22, 80, 443 | [`lab-02-scan-antes.txt`](evidence/lab-02-scan-antes.txt) → [`lab-06-scan-despues.txt`](evidence/lab-06-scan-despues.txt) |
| `ssh-test` con la misma clave válida | root **ENTRA** (`uid=0(root)`); `trackflow-ops` denegado (no existe) | root **DENEGADO** (`Permission denied (publickey)`); `trackflow-ops` **ENTRA** (`uid=1001`, grupo `sudo`) | [`lab-03-ssh-antes.txt`](evidence/lab-03-ssh-antes.txt) → [`lab-07-ssh-despues.txt`](evidence/lab-07-ssh-despues.txt) |
| `harden` | — | Usuarios creados, drop-in validado con `sshd -t`, permisos, ufw activo, claves de root eliminadas | [`lab-04-harden.txt`](evidence/lab-04-harden.txt) |
| Permisos (`ls -la`) | `777` | `app` `drwxr-x---` `trackflow-ops:trackflow`, `config` `drwxr-x---` `root:trackflow`, `logs` `drwxr-s---` `trackflow:trackflow-ops`, `.env` `-rw-r-----` `root:trackflow` | [`lab-08-permisos.txt`](evidence/lab-08-permisos.txt) |
| `ufw status verbose` | `inactive` | `deny (incoming), allow (outgoing)`; `22/tcp LIMIT`, `80/tcp ALLOW`, `443/tcp ALLOW` (IPv4 e IPv6) | [`lab-09-ufw.txt`](evidence/lab-09-ufw.txt) |
| `down` + `space` | — | Contenedor, red e imagen borrados; 20 GB libres | [`lab-10-limpieza.txt`](evidence/lab-10-limpieza.txt) |

La parte estática (opciones del drop-in, usuarios, permisos y reglas de `harden.sh`, `bash -n` de los scripts, que la clave de laboratorio no está en el repo) se comprueba en cada ejecución de la suite con `tests/test_owasp_hardening.py`.

**Clave de laboratorio:** el `docker build` genera una clave ed25519 en `/opt/lab-keys/`, solo dentro de la imagen, para demostrar un login real de root en el «antes». No está en el repo y desaparece con `lab.sh down`.

## 6. Cómo se aplica en un VPS real

Resumen; el procedimiento completo está en el [README de `infra/hardening/`](../../infra/hardening/README.md#cómo-se-aplica-en-un-vps-real).

1. Genera la clave de operaciones en tu equipo (`ssh-keygen -t ed25519`) y copia al servidor, **con el acceso que ya tienes**, `harden.sh`, `audit.sh`, el drop-in y la clave pública (`scp`).
2. En el servidor: `sudo bash harden.sh --ops-pubkey <clave.pub>`, después `sudo passwd trackflow-ops` (la contraseña que pedirá `sudo`) y `sudo bash audit.sh` (debe dar `FAIL=0`).
3. **Antes de cerrar la sesión actual**, comprueba en otra terminal que `ssh trackflow-ops@servidor` entra y que `sudo -v` pide la contraseña. Si algo falla, todavía tienes la sesión original para corregirlo.

Diferencias con el laboratorio: `sshd` se recarga con `systemctl reload ssh`, no hace falta el ajuste de `IPT_SYSCTL` (en el contenedor `/proc/sys` es de solo lectura) y `ufw --force reset` borra las reglas previas.

## 7. Fuera de alcance

- **Proxy inverso con TLS en el 443** (Caddy o Nginx con Let's Encrypt): publicaría la API, los frontends y `/mcp`, y redirigiría el 80 a HTTPS. La API ya envía HSTS cuando la petición llega por HTTPS (`X-Forwarded-Proto: https`).
- **Autenticación en Redis y Qdrant** (`requirepass`, `QDRANT__SERVICE__API_KEY`): recomendada como defensa en profundidad. Hoy los protegen el firewall y el *bind* en loopback.
- **fail2ban, actualizaciones automáticas (`unattended-upgrades`) y envío centralizado de logs**: siguientes pasos recomendados.
- **El Codespace** (`sshd` en 2222 con `PermitRootLogin yes`, `vscode` con sudo sin contraseña) no se toca: es un entorno de desarrollo, sin reenvío del 2222 y con acceso solo desde la cuenta de GitHub.
