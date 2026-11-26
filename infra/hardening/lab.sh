#!/usr/bin/env bash
# TrackFlow · orquestador del laboratorio de endurecimiento del servidor (D1, D7).
#
#   infra/hardening/lab.sh <subcomando>
#
#   space     espacio en disco (df -h / y docker system df)
#   up        crea la red, construye la imagen y arranca el servidor (estado inseguro por defecto)
#   audit     ejecuta audit.sh dentro del servidor (PASS/FAIL por control)
#   scan      escanea los 11 puertos de la pila desde un cliente de la red
#   ssh-test  intenta entrar por SSH como root y como trackflow-ops con la clave de laboratorio
#   harden    copia harden.sh y el drop-in de SSH al servidor y los aplica (--lab)
#   down      borra el contenedor, la red y la imagen (recupera el disco)
#
# Sin puertos publicados: al servidor solo se llega desde la red trackflow-hardening-net.
# Los scripts se pasan con `docker cp` o por stdin (no con -v): el Docker del Codespace es el
# del host (docker-outside-of-docker) y no ve las rutas del workspace.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="trackflow-server-sim"
NETWORK="trackflow-hardening-net"
CONTAINER="trackflow-server"
REMOTE_DIR="/tmp/trackflow-hardening"
LAB_KEY="/opt/lab-keys/id_ed25519"

die() { printf '[lab] ERROR: %s\n' "$*" >&2; exit 1; }

header() {
    printf '\n=== lab.sh %s · %s ===\n' "$1" "$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
}

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

container_running() {
    [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)" == "true" ]]
}

require_container() {
    container_running || die "el servidor $CONTAINER no está arrancado: ejecuta 'lab.sh up'"
}

# La misma imagen hace de cliente en la red del laboratorio.
client() {
    docker run --rm -i --network "$NETWORK" "$IMAGE" "$@"
}

cmd_space() {
    header space
    df -h /
    echo
    docker system df
}

cmd_up() {
    header up
    if ! docker network inspect "$NETWORK" >/dev/null 2>&1; then
        docker network create "$NETWORK" >/dev/null
        echo "red $NETWORK creada"
    fi
    docker build -t "$IMAGE" "$SCRIPT_DIR/server-sim"
    if container_running; then
        echo "$CONTAINER ya estaba arrancado"
    else
        docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
        docker run -d --name "$CONTAINER" --hostname "$CONTAINER" --network "$NETWORK" \
            --cap-add NET_ADMIN "$IMAGE" >/dev/null
        echo "$CONTAINER arrancado (sin puertos publicados, con NET_ADMIN para ufw)"
    fi
    for _ in $(seq 1 20); do
        if docker exec "$CONTAINER" bash -c 'exec 3<>/dev/tcp/127.0.0.1/22' 2>/dev/null; then
            docker ps --filter "name=^${CONTAINER}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
            return 0
        fi
        sleep 0.5
    done
    docker logs "$CONTAINER" | tail -20
    die "sshd no responde en $CONTAINER"
}

cmd_audit() {
    header audit
    require_container
    docker exec -i "$CONTAINER" bash -s < "$SCRIPT_DIR/audit.sh" || echo "(hay controles en FAIL)"
}

cmd_scan() {
    header scan
    require_container
    client bash -s -- "$CONTAINER" < "$SCRIPT_DIR/scan_ports.sh"
}

cmd_ssh_test() {
    header ssh-test
    require_container
    client bash -s -- "$CONTAINER" "$LAB_KEY" <<'EOF'
host="$1"; key="$2"
opts=(-i "$key" -o BatchMode=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
      -o ConnectTimeout=5 -o LogLevel=ERROR)
for user in root trackflow-ops; do
    if out="$(ssh "${opts[@]}" "$user@$host" id 2>&1)"; then
        echo "ENTRA     ssh -i $key $user@$host id → $out"
    else
        echo "DENEGADO  ssh -i $key $user@$host id → $(tail -1 <<<"$out")"
    fi
done
# Métodos de autenticación que ofrece el servidor (sin clave, sin contraseña: solo pregunta).
methods="$(ssh -o BatchMode=yes -o PubkeyAuthentication=no -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 "probe@$host" true 2>&1 | grep -o 'Permission denied ([^)]*)' || true)"
echo "MÉTODOS   el servidor ofrece: ${methods:-(sin respuesta)}"
EOF
}

cmd_harden() {
    header harden
    require_container
    docker exec "$CONTAINER" mkdir -p "$REMOTE_DIR/sshd_config.d"
    docker cp "$SCRIPT_DIR/harden.sh" "$CONTAINER:$REMOTE_DIR/harden.sh"
    docker cp "$SCRIPT_DIR/sshd_config.d/10-trackflow-hardening.conf" \
        "$CONTAINER:$REMOTE_DIR/sshd_config.d/10-trackflow-hardening.conf"
    docker exec "$CONTAINER" bash "$REMOTE_DIR/harden.sh" --lab
}

cmd_down() {
    header down
    docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "contenedor $CONTAINER borrado" || echo "sin contenedor $CONTAINER"
    docker network rm "$NETWORK" >/dev/null 2>&1 && echo "red $NETWORK borrada" || echo "sin red $NETWORK"
    docker image rm "$IMAGE" >/dev/null 2>&1 && echo "imagen $IMAGE borrada" || echo "sin imagen $IMAGE"
    echo "La imagen base ubuntu:24.04 se conserva; si no la usas para nada más: docker image rm ubuntu:24.04"
}

case "${1:-}" in
    space) cmd_space ;;
    up) cmd_up ;;
    audit) cmd_audit ;;
    scan) cmd_scan ;;
    ssh-test) cmd_ssh_test ;;
    harden) cmd_harden ;;
    down) cmd_down ;;
    -h|--help|help|"") usage ;;
    *) usage; die "subcomando desconocido: $1" ;;
esac
