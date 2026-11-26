#!/usr/bin/env bash
# TrackFlow · escaneo de puertos TCP desde un cliente de la red del laboratorio (D7).
#
#   bash scan_ports.sh <host> [puerto …]
#
# Sin puertos, revisa los 11 de la pila. Usa `bash /dev/tcp` con `timeout 2`: ABIERTO si el
# connect termina; CERRADO si se rechaza o el firewall descarta el paquete (filtrado).
set -uo pipefail

HOST="${1:-trackflow-server}"
shift || true
DEFAULT_PORTS=(22 80 443 3000 3001 3002 5555 6333 6379 8000 8001)
if [[ $# -gt 0 ]]; then PORTS=("$@"); else PORTS=("${DEFAULT_PORTS[@]}"); fi

declare -A SERVICE=(
    [22]="SSH" [80]="HTTP" [443]="HTTPS" [3000]="website" [3001]="backoffice" [3002]="application"
    [5555]="Flower" [6333]="Qdrant" [6379]="Redis" [8000]="API" [8001]="MCP"
)

printf '=== scan_ports.sh · %s · destino %s ===\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')" "$HOST"
open=()
for port in "${PORTS[@]}"; do
    if timeout 2 bash -c "exec 3<>/dev/tcp/$HOST/$port" 2>/dev/null; then
        state="ABIERTO"
        open+=("$port")
    else
        state="CERRADO"
    fi
    printf '%-6s %-12s %s\n' "$port" "${SERVICE[$port]:-?}" "$state"
done
printf 'Abiertos: %d de %d (%s)\n' "${#open[@]}" "${#PORTS[@]}" "${open[*]:-ninguno}"
