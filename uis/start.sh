#!/bin/sh
set -e

(
  cd /app/website
  npm run dev -- --hostname 0.0.0.0 --port 3000
) &
website_pid=$!

(
  cd /app/backoffice
  npm run dev -- --hostname 0.0.0.0 --port 3001
) &
backoffice_pid=$!

shutdown() {
  kill "$website_pid" "$backoffice_pid" 2>/dev/null || true
}
trap shutdown INT TERM

wait "$website_pid" "$backoffice_pid"