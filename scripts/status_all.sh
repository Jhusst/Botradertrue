#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${ROOT}/logs"

status_pid() {
  local name="$1"
  local pidfile="$2"
  if [[ -f "${pidfile}" ]] && kill -0 "$(cat "${pidfile}")" 2>/dev/null; then
    echo "${name}: activo (PID $(cat "${pidfile}"))"
  else
    echo "${name}: detenido"
  fi
}

status_pid "Ollama" "${LOG_DIR}/ollama.pid"
status_pid "API" "${LOG_DIR}/api.pid"

if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:8000/dashboard"; then
  echo "Dashboard: http://localhost:8000/dashboard"
else
  echo "Dashboard: no responde en :8000"
fi

"${ROOT}/scripts/check_binance_ip.sh" || true
