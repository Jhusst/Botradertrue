#!/usr/bin/env bash
# Arranca Ollama + API del bot en segundo plano (sin systemd).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${ROOT}/logs"
mkdir -p "${LOG_DIR}"

OLLAMA_PID="${LOG_DIR}/ollama.pid"
API_PID="${LOG_DIR}/api.pid"

is_running() {
  local pidfile="$1"
  [[ -f "${pidfile}" ]] || return 1
  local pid
  pid="$(cat "${pidfile}")"
  kill -0 "${pid}" 2>/dev/null
}

start_ollama() {
  if is_running "${OLLAMA_PID}"; then
    echo "Ollama ya corre (PID $(cat "${OLLAMA_PID}"))"
    return
  fi
  nohup "${ROOT}/scripts/run_ollama.sh" >> "${LOG_DIR}/ollama.log" 2>&1 &
  echo $! > "${OLLAMA_PID}"
  echo "Ollama iniciado (PID $(cat "${OLLAMA_PID}")) → ${LOG_DIR}/ollama.log"
}

start_api() {
  if is_running "${API_PID}"; then
    echo "API ya corre (PID $(cat "${API_PID}"))"
    return
  fi
  nohup "${ROOT}/scripts/run_api_prod.sh" >> "${LOG_DIR}/api.log" 2>&1 &
  echo $! > "${API_PID}"
  echo "API iniciada (PID $(cat "${API_PID}")) → http://localhost:8000/dashboard"
  echo "Logs: ${LOG_DIR}/api.log"
}

start_ollama
sleep 2
start_api
"${ROOT}/scripts/check_binance_ip.sh" || true
