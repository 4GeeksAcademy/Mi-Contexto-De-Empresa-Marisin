#!/usr/bin/env bash
# TrackFlow · auditoría del endurecimiento del servidor (D7).
#
# Se ejecuta DENTRO del servidor como root (lab.sh audit lo pasa por stdin con docker exec):
#   bash audit.sh
# Imprime una línea PASS/FAIL por control y sale con 1 si alguno falla. Solo lee: no cambia nada.
set -uo pipefail

OPS_USER="trackflow-ops"
SERVICE_USER="trackflow"
BASE_DIR="/srv/trackflow"

PASSES=0
FAILS=0

check() {
    # check "<descripción>" "<esperado>" "<obtenido>"
    local description="$1" expected="$2" obtained="$3"
    if [[ "$obtained" == "$expected" ]]; then
        PASSES=$((PASSES + 1))
        printf 'PASS  %-52s %s\n' "$description" "$obtained"
    else
        FAILS=$((FAILS + 1))
        printf 'FAIL  %-52s obtenido=%s · esperado=%s\n' "$description" "${obtained:-(vacío)}" "$expected"
    fi
}

sshd_value() {
    sshd -T 2>/dev/null | awk -v key="$1" '$1 == key { $1 = ""; sub(/^ /, ""); print; exit }'
}

mode_owner() {
    if [[ -e "$1" ]]; then stat -c '%a %U:%G' "$1"; else echo "(no existe)"; fi
}

user_shell() {
    getent passwd "$1" | cut -d: -f7
}

in_group() {
    if id -nG "$1" 2>/dev/null | tr ' ' '\n' | grep -qx "$2"; then echo si; else echo no; fi
}

printf '=== audit.sh · %s · %s ===\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')" "$(hostname)"

echo "--- SSH (configuración efectiva: sshd -T) ---"
mkdir -p /run/sshd
check "PermitRootLogin" "no" "$(sshd_value permitrootlogin)"
check "PasswordAuthentication" "no" "$(sshd_value passwordauthentication)"
check "KbdInteractiveAuthentication" "no" "$(sshd_value kbdinteractiveauthentication)"
check "AuthenticationMethods" "publickey" "$(sshd_value authenticationmethods)"
check "AllowUsers" "$OPS_USER" "$(sshd_value allowusers)"
check "MaxAuthTries" "3" "$(sshd_value maxauthtries)"
check "X11Forwarding" "no" "$(sshd_value x11forwarding)"
check "AllowTcpForwarding" "no" "$(sshd_value allowtcpforwarding)"
if [[ -s /root/.ssh/authorized_keys ]]; then root_keys="si"; else root_keys="no"; fi
check "root tiene claves SSH autorizadas" "no" "$root_keys"

echo "--- Usuarios ---"
check "solo root tiene uid 0" "root" "$(awk -F: '$3 == 0 { print $1 }' /etc/passwd | paste -sd, -)"
check "$OPS_USER existe con shell bash" "/bin/bash" "$(user_shell "$OPS_USER")"
check "$OPS_USER en el grupo sudo" "si" "$(in_group "$OPS_USER" sudo)"
check "$OPS_USER fuera del grupo $SERVICE_USER" "no" "$(in_group "$OPS_USER" "$SERVICE_USER")"
if grep -rEs '^[^#]*NOPASSWD' /etc/sudoers /etc/sudoers.d | grep -Eq "(%sudo|$OPS_USER)"; then nopasswd="si"; else nopasswd="no"; fi
check "sudo sin contraseña (NOPASSWD) para ops/%sudo" "no" "$nopasswd"
ops_home="$(getent passwd "$OPS_USER" | cut -d: -f6)"
if [[ -n "$ops_home" && -s "$ops_home/.ssh/authorized_keys" ]]; then ops_keys="si"; else ops_keys="no"; fi
check "$OPS_USER tiene clave SSH autorizada" "si" "$ops_keys"
check "$SERVICE_USER existe con shell nologin" "/usr/sbin/nologin" "$(user_shell "$SERVICE_USER")"
check "$SERVICE_USER fuera del grupo sudo" "no" "$(in_group "$SERVICE_USER" sudo)"

echo "--- Permisos de $BASE_DIR ---"
check "$BASE_DIR" "755 root:root" "$(mode_owner "$BASE_DIR")"
check "$BASE_DIR/app (código)" "750 $OPS_USER:$SERVICE_USER" "$(mode_owner "$BASE_DIR/app")"
check "$BASE_DIR/logs" "2750 $SERVICE_USER:$OPS_USER" "$(mode_owner "$BASE_DIR/logs")"
check "$BASE_DIR/config (configuración sensible)" "750 root:$SERVICE_USER" "$(mode_owner "$BASE_DIR/config")"
check "$BASE_DIR/config/.env" "640 root:$SERVICE_USER" "$(mode_owner "$BASE_DIR/config/.env")"
loose_files="$(find "$BASE_DIR/app" -type f ! -perm 640 2>/dev/null | wc -l)"
check "ficheros de app/ con permisos distintos de 640" "0" "$loose_files"
world_writable="$(find "$BASE_DIR" -perm -o+w 2>/dev/null | wc -l)"
check "rutas escribibles por cualquiera en $BASE_DIR" "0" "$world_writable"

echo "--- Firewall (ufw) ---"
ufw_status="$(ufw status verbose 2>/dev/null || true)"
check "ufw activo" "Status: active" "$(grep -m1 '^Status:' <<<"$ufw_status")"
check "política por defecto de entrada" "deny (incoming)" "$(grep -o 'deny (incoming)' <<<"$ufw_status" | head -1)"
check "política por defecto de salida" "allow (outgoing)" "$(grep -o 'allow (outgoing)' <<<"$ufw_status" | head -1)"
rules="$(ufw status 2>/dev/null | awk '/^[0-9]+\/tcp / && $0 !~ /\(v6\)/ { print $1 "=" $2 }' | paste -sd' ' -)"
check "reglas de entrada (solo 22 limit, 80, 443)" "22/tcp=LIMIT 80/tcp=ALLOW 443/tcp=ALLOW" "$rules"

echo "--- Resultado ---"
printf 'PASS=%d FAIL=%d\n' "$PASSES" "$FAILS"
[[ "$FAILS" -eq 0 ]]
