# Endurecimiento del servidor (laboratorio)

Laboratorio reproducible que simula el VPS de producción de TrackFlow en Docker y
demuestra, con el mismo comando antes y después, la línea base del servidor:

- **SSH sin root** y solo con clave pública (`sshd_config.d/10-trackflow-hardening.conf`).
- **Usuarios dedicados sin root:** `trackflow-ops` para las personas de operaciones
  (bash, `sudo` **con** contraseña, SSH solo con clave) y `trackflow` como cuenta de
  servicio (`nologin`, sin sudo y sin home).
- **Permisos de carpetas explícitos** en `/srv/trackflow`:

  | Ruta | Modo | Dueño | Para qué |
  |------|------|-------|----------|
  | `/srv/trackflow` | `755` | `root:root` | raíz |
  | `app/` | `750` (ficheros `640`) | `trackflow-ops:trackflow` | código: ops despliega, el servicio solo lee |
  | `logs/` | `2750` | `trackflow:trackflow-ops` | escribe el servicio, ops lee |
  | `config/` | `750` | `root:trackflow` | configuración sensible |
  | `config/.env` | `640` | `root:trackflow` | secretos: solo root los cambia y el servicio los lee; **ops no** |

  El servicio corre con `UMask=0027` (`/etc/systemd/system/trackflow-api.service.d/10-hardening.conf`).
- **Firewall (ufw):** `deny incoming` y `allow outgoing`. Solo se abren `22/tcp`
  (`limit`, SSH de ops con freno a la fuerza bruta), `80/tcp` (solo redirección a HTTPS)
  y `443/tcp` (API y frontend detrás del proxy inverso). Quedan **cerrados** 3000–3002,
  8000, 8001 (el MCP se publicaría como ruta `/mcp` del 443), 5555 (Flower), 6333
  (Qdrant) y 6379 (Redis).

La justificación completa y los resultados están en `docs/owasp/server-hardening.md`.

## Ficheros

| Fichero | Qué hace |
|---------|----------|
| `server-sim/Dockerfile` | Imagen `trackflow-server-sim` (Ubuntu 24.04 + `openssh-server`, `openssh-client`, `ufw`, `iptables`, `sudo`, `netcat-openbsd`) con la configuración por defecto **insegura a propósito** |
| `server-sim/entrypoint.sh` | Arranca listeners en los puertos de la pila (80, 443, 3000–3002, 5555, 6333, 6379, 8000, 8001) y `sshd` en el 22 |
| `sshd_config.d/10-trackflow-hardening.conf` | Drop-in de SSH (D4) |
| `harden.sh` | Endurece el servidor de forma idempotente: usuarios, SSH (`sshd -t` antes de recargar), permisos, firewall y quita las claves de root |
| `audit.sh` | Una línea PASS/FAIL por control (se ejecuta dentro del servidor; solo lee) |
| `scan_ports.sh` | ABIERTO/CERRADO por puerto desde un cliente (`bash /dev/tcp`, `timeout 2`) |
| `lab.sh` | Orquestador del laboratorio |

## Uso

```bash
infra/hardening/lab.sh space      # espacio en disco antes de construir nada
infra/hardening/lab.sh up         # red + imagen + servidor (estado inseguro)
infra/hardening/lab.sh audit      # antes: FAIL en SSH, usuarios, permisos y ufw
infra/hardening/lab.sh scan       # antes: 11 puertos abiertos
infra/hardening/lab.sh ssh-test   # antes: root ENTRA
infra/hardening/lab.sh harden     # aplica harden.sh --lab
infra/hardening/lab.sh audit      # después: todo PASS
infra/hardening/lab.sh scan       # después: solo 22, 80 y 443
infra/hardening/lab.sh ssh-test   # después: root DENEGADO, trackflow-ops ENTRA
infra/hardening/lab.sh down       # borra contenedor, red e imagen
```

- La imagen hace a la vez de servidor (`trackflow-server`, con `--cap-add NET_ADMIN`
  para que ufw pueda programar iptables) y de cliente/escáner (`docker run --rm` en la
  red `trackflow-hardening-net`). **No publica ningún puerto** al Codespace.
- Los scripts entran en el contenedor con `docker cp` o por stdin, nunca con `-v`: en
  el Codespace el Docker es el del host (*docker-outside-of-docker*) y no ve las rutas
  del workspace. Así lo que se prueba es exactamente el fichero del repo.
- En el contenedor, `/proc/sys` es de solo lectura: `harden.sh --lab` apunta
  `IPT_SYSCTL` de `/etc/default/ufw` a un fichero vacío. En un VPS real no hace falta.

> ⚠️ **Clave de laboratorio.** El `docker build` genera una clave ed25519 en
> `/opt/lab-keys/` y la autoriza para `root`. Así el «antes» demuestra un login real
> de root por SSH. Esa clave vive **solo dentro de la imagen**, no se guarda en el repo
> y desaparece con `lab.sh down`. Es una credencial de laboratorio: no la copies a
> ningún servidor real.

## Cómo se aplica en un VPS real

1. Crea en tu equipo la clave de operaciones (`ssh-keygen -t ed25519`) y súbela junto
   con los scripts, todavía con tu acceso actual:
   ```bash
   scp -r infra/hardening/harden.sh infra/hardening/sshd_config.d infra/hardening/audit.sh \
       ~/.ssh/id_ed25519.pub usuario@servidor:/tmp/trackflow-hardening/
   ```
2. En el servidor:
   ```bash
   sudo bash /tmp/trackflow-hardening/harden.sh --ops-pubkey /tmp/trackflow-hardening/id_ed25519.pub
   sudo passwd trackflow-ops        # la contraseña que pedirá sudo
   sudo bash /tmp/trackflow-hardening/audit.sh
   ```
3. **Antes de cerrar la sesión actual**, comprueba en otra terminal que entras con
   `ssh trackflow-ops@servidor` y que `sudo -v` te pide la contraseña.

Diferencias con el laboratorio:

- `harden.sh` recarga `sshd` con `systemctl reload ssh`.
- No hace falta el truco de `IPT_SYSCTL`.
- `ufw --force reset` borra las reglas que hubiera, así que la política queda exactamente la descrita.

Queda **fuera de alcance**, y se documenta como siguiente paso, el proxy inverso con
TLS en el 443 (por ejemplo, Caddy o Nginx con Let's Encrypt), que publicaría la API,
el frontend y `/mcp`.
