#!/usr/bin/env bash
# Arranque del servidor de laboratorio (D2): listeners que simulan la pila y sshd en primer plano.
set -euo pipefail

# 22 lo atiende sshd; el resto simula los servicios de la pila:
# 80/443 proxy inverso · 3000-3002 frontends · 5555 Flower · 6333 Qdrant · 6379 Redis · 8000 API · 8001 MCP
STACK_PORTS=(80 443 3000 3001 3002 5555 6333 6379 8000 8001)

ssh-keygen -A >/dev/null
mkdir -p /run/sshd

for port in "${STACK_PORTS[@]}"; do
    nc -dlk "$port" >/dev/null 2>&1 &
done

echo "trackflow-server listo: sshd en 22 y listeners en ${STACK_PORTS[*]}"
exec /usr/sbin/sshd -D -e
