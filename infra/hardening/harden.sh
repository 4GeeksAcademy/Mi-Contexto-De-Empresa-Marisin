#!/usr/bin/env bash
# TrackFlow · endurecimiento del servidor (D3, D4, D5, D6).
#
# Idempotente: se puede ejecutar varias veces y siempre deja el mismo estado.
#
#   sudo bash harden.sh --ops-pubkey /ruta/id_ed25519.pub   # VPS real
#   bash harden.sh --lab                                    # contenedor de laboratorio (lab.sh harden)
#
# (a) usuarios: trackflow-ops (operaciones: bash, sudo CON contraseña, SSH solo con clave)
#     y trackflow (cuenta de servicio: nologin, sin sudo, sin home);
# (b) SSH: instala sshd_config.d/10-trackflow-hardening.conf, valida con `sshd -t` y recarga;
# (c) permisos de /srv/trackflow (código, logs y configuración sensible);
# (d) firewall ufw: deny incoming; solo 22 (limit), 80 y 443;
# (e) quita las claves autorizadas de root.
#
# --lab: usa la clave de laboratorio /opt/lab-keys/id_ed25519.pub para trackflow-ops y
# apunta IPT_SYSCTL de ufw a un fichero vacío (el /proc/sys del contenedor es de solo lectura).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SSH_DROPIN_SRC="$SCRIPT_DIR/sshd_config.d/10-trackflow-hardening.conf"
SSH_DROPIN_DST="/etc/ssh/sshd_config.d/10-trackflow-hardening.conf"
LAB_PUBKEY="/opt/lab-keys/id_ed25519.pub"

OPS_USER="trackflow-ops"
SERVICE_USER="trackflow"
BASE_DIR="/srv/trackflow"
SERVICE_DROPIN="/etc/systemd/system/trackflow-api.service.d/10-hardening.conf"
UFW_DEFAULTS="/etc/default/ufw"
UFW_LAB_SYSCTL="/etc/ufw/sysctl-lab.conf"

LAB=0
OPS_PUBKEY=""

log() { printf '[harden] %s\n' "$*"; }
die() { printf '[harden] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
    sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --lab) LAB=1; shift ;;
        --ops-pubkey) OPS_PUBKEY="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) die "opción desconocida: $1 (usa --help)" ;;
    esac
done

[[ "$(id -u)" -eq 0 ]] || die "hay que ejecutarlo como root (sudo bash harden.sh …)"
[[ -f "$SSH_DROPIN_SRC" ]] || die "no encuentro $SSH_DROPIN_SRC"
if [[ "$LAB" -eq 1 && -z "$OPS_PUBKEY" ]]; then
    OPS_PUBKEY="$LAB_PUBKEY"
fi

printf '=== harden.sh · %s · modo %s ===\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')" "$([[ $LAB -eq 1 ]] && echo laboratorio || echo servidor)"

# --------------------------------------------------------------------------- #
# (a) Usuarios
# --------------------------------------------------------------------------- #
setup_users() {
    # Cuenta de servicio: dueña de los procesos de la API; nadie entra con ella.
    if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
        useradd --system --user-group --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin "$SERVICE_USER"
        log "creada la cuenta de servicio $SERVICE_USER (nologin, sin home)"
    fi
    usermod --shell /usr/sbin/nologin "$SERVICE_USER"
    gpasswd -d "$SERVICE_USER" sudo >/dev/null 2>&1 || true

    # Usuario humano de operaciones: entra por SSH con clave y eleva con sudo + contraseña.
    if ! id -u "$OPS_USER" >/dev/null 2>&1; then
        useradd --create-home --user-group --shell /bin/bash "$OPS_USER"
        log "creado el usuario de operaciones $OPS_USER"
    fi
    usermod --shell /bin/bash "$OPS_USER"
    usermod -aG sudo "$OPS_USER"
    # ops NO pertenece al grupo del servicio: así no lee config/.env (D5).
    gpasswd -d "$OPS_USER" "$SERVICE_USER" >/dev/null 2>&1 || true

    # sudo con contraseña: el grupo sudo de Ubuntu ya la pide; no se tolera NOPASSWD.
    if grep -rEs '^[^#]*NOPASSWD' /etc/sudoers /etc/sudoers.d | grep -Eq "(%sudo|$OPS_USER)"; then
        die "hay una regla NOPASSWD para %sudo o $OPS_USER: quítala antes de continuar"
    fi
    log "$OPS_USER: grupo sudo, sudo con contraseña (fíjala con 'passwd $OPS_USER' desde la consola)"

    # Clave autorizada de ops (sin ella no se quitan las de root: no te quedas fuera).
    local ops_home ssh_dir keys
    ops_home="$(getent passwd "$OPS_USER" | cut -d: -f6)"
    ssh_dir="$ops_home/.ssh"
    keys="$ssh_dir/authorized_keys"
    install -d -m 700 -o "$OPS_USER" -g "$OPS_USER" "$ssh_dir"
    touch "$keys"
    if [[ -n "$OPS_PUBKEY" ]]; then
        [[ -s "$OPS_PUBKEY" ]] || die "no encuentro la clave pública $OPS_PUBKEY"
        grep -qxF "$(cat "$OPS_PUBKEY")" "$keys" || cat "$OPS_PUBKEY" >> "$keys"
    fi
    chown "$OPS_USER:$OPS_USER" "$keys"
    chmod 600 "$keys"
    [[ -s "$keys" ]] || die "$OPS_USER no tiene ninguna clave autorizada: usa --ops-pubkey"
    log "$OPS_USER: $(grep -c . "$keys") clave(s) autorizada(s)"
}

# --------------------------------------------------------------------------- #
# (b) SSH
# --------------------------------------------------------------------------- #
reload_sshd() {
    if [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null 2>&1; then
        systemctl reload ssh 2>/dev/null || systemctl restart ssh
    elif [[ -s /run/sshd.pid ]]; then
        kill -HUP "$(cat /run/sshd.pid)"
    elif [[ "$LAB" -eq 1 ]]; then
        kill -HUP 1   # en el laboratorio sshd es el PID 1 (exec del entrypoint)
    else
        die "no sé cómo recargar sshd: recárgalo a mano"
    fi
}

setup_ssh() {
    local backup=""
    if [[ -f "$SSH_DROPIN_DST" ]]; then
        backup="$(mktemp)"
        cp -p "$SSH_DROPIN_DST" "$backup"
    fi
    install -D -m 644 -o root -g root "$SSH_DROPIN_SRC" "$SSH_DROPIN_DST"
    mkdir -p /run/sshd
    if ! sshd -t; then
        if [[ -n "$backup" ]]; then mv "$backup" "$SSH_DROPIN_DST"; else rm -f "$SSH_DROPIN_DST"; fi
        die "sshd -t rechaza la configuración: se deja la anterior y no se recarga"
    fi
    if [[ -n "$backup" ]]; then rm -f "$backup"; fi
    reload_sshd
    log "SSH: drop-in instalado, validado con sshd -t y sshd recargado"
}

# --------------------------------------------------------------------------- #
# (c) Permisos de carpetas (D5)
# --------------------------------------------------------------------------- #
setup_permissions() {
    install -d -m 755 -o root -g root "$BASE_DIR"
    install -d -o "$OPS_USER" -g "$SERVICE_USER" "$BASE_DIR/app"
    install -d -o "$SERVICE_USER" -g "$OPS_USER" "$BASE_DIR/logs"
    install -d -o root -g "$SERVICE_USER" "$BASE_DIR/config"

    # app/: código. ops despliega, el servicio solo lee, nadie más.
    chown -R "$OPS_USER:$SERVICE_USER" "$BASE_DIR/app"
    find "$BASE_DIR/app" -type d -exec chmod 750 {} +
    find "$BASE_DIR/app" -type f -exec chmod 640 {} +

    # logs/: escribe el servicio, ops lee. setgid: los ficheros nuevos heredan el grupo ops.
    chown -R "$SERVICE_USER:$OPS_USER" "$BASE_DIR/logs"
    chmod 2750 "$BASE_DIR/logs"
    find "$BASE_DIR/logs" -mindepth 1 -type d -exec chmod 2750 {} +
    find "$BASE_DIR/logs" -type f -exec chmod 640 {} +

    # config/: secretos. Solo root los cambia (sudo); el servicio los lee; ops no.
    [[ -f "$BASE_DIR/config/.env" ]] || install -m 640 -o root -g "$SERVICE_USER" /dev/null "$BASE_DIR/config/.env"
    chown -R "root:$SERVICE_USER" "$BASE_DIR/config"
    chmod 750 "$BASE_DIR/config"
    find "$BASE_DIR/config" -mindepth 1 -type d -exec chmod 750 {} +
    find "$BASE_DIR/config" -type f -exec chmod 640 {} +

    # umask 027 para el servicio: lo que cree no será legible por «otros».
    install -d -m 755 "$(dirname "$SERVICE_DROPIN")"
    cat > "$SERVICE_DROPIN" <<EOF
# TrackFlow · el servicio de la API corre sin privilegios (D5). Generado por harden.sh.
[Service]
User=$SERVICE_USER
Group=$SERVICE_USER
UMask=0027
WorkingDirectory=$BASE_DIR/app
EnvironmentFile=$BASE_DIR/config/.env
EOF
    chmod 644 "$SERVICE_DROPIN"
    log "permisos: app 750/640, logs 2750, config 750 y .env 640; umask 027 en $SERVICE_DROPIN"
}

# --------------------------------------------------------------------------- #
# (d) Firewall (D6)
# --------------------------------------------------------------------------- #
setup_firewall() {
    if [[ "$LAB" -eq 1 ]]; then
        : > "$UFW_LAB_SYSCTL"
        if grep -q '^IPT_SYSCTL=' "$UFW_DEFAULTS"; then
            sed -i "s|^IPT_SYSCTL=.*|IPT_SYSCTL=$UFW_LAB_SYSCTL|" "$UFW_DEFAULTS"
        else
            echo "IPT_SYSCTL=$UFW_LAB_SYSCTL" >> "$UFW_DEFAULTS"
        fi
        log "ufw (laboratorio): IPT_SYSCTL=$UFW_LAB_SYSCTL"
    fi

    # Parte de cero en cada ejecución: la política queda exactamente así.
    ufw --force reset >/dev/null
    ufw default deny incoming
    ufw default allow outgoing
    ufw limit 22/tcp comment 'SSH solo ops (anti fuerza bruta)'
    ufw allow 80/tcp comment 'HTTP solo redireccion a HTTPS'
    ufw allow 443/tcp comment 'HTTPS API y frontend (proxy inverso)'
    # Cerrados (no hay regla): 3000-3002 frontends, 8000 API, 8001 MCP, 5555 Flower, 6333 Qdrant, 6379 Redis.
    ufw --force enable || die "ufw enable falló: STOP (D6) y se decide el plan B (nftables)"
    log "firewall: deny incoming; abiertos solo 22 (limit), 80 y 443"
}

# --------------------------------------------------------------------------- #
# (e) Root sin claves autorizadas
# --------------------------------------------------------------------------- #
remove_root_keys() {
    if [[ -e /root/.ssh/authorized_keys ]]; then
        rm -f /root/.ssh/authorized_keys
        log "root: claves autorizadas eliminadas"
    else
        log "root: sin claves autorizadas"
    fi
}

setup_users
setup_ssh
setup_permissions
setup_firewall
remove_root_keys
log "hecho. Comprueba con audit.sh (y en un VPS, entra como $OPS_USER en otra sesión antes de cerrar esta)."
