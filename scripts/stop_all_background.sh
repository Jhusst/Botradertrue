#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${ROOT}/logs"

stop_pidfile() {
  local name="$1"
  local pidfile="$2"
  if [[ ! -f "${pidfile}" ]]; then
    echo "${name}: no hay PID file"
    return
  fi
  local pid
  pid="$(cat "${pidfile}")"
  if kill -0 "${pid}" 2>/dev/null; then
    kill "${pid}" 2>/dev/null || true
    sleep 1
    kill -9 "${pid}" 2>/dev/null || true
    echo "${name} detenido (PID ${pid})"
  else
    echo "${name}: proceso no activo"
  fi
  rm -f "${pidfile}"
}

stop_pidfile "API" "${LOG_DIR}/api.pid"
stop_pidfile "Ollama" "${LOG_DIR}/ollama.pid"

pkill -f "uvicorn trading_bot.main:app" 2>/dev/null || true
