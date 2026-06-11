#!/usr/bin/env bash
# Muestra tu IP pública y avisa si cambió (Binance whitelist).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${ROOT}/.cursor/hooks/state"
LAST_IP_FILE="${STATE_DIR}/last-public-ip.txt"
mkdir -p "${STATE_DIR}"

CURRENT_IP="$(curl -s --max-time 8 https://api.ipify.org || true)"
if [[ -z "${CURRENT_IP}" ]]; then
  echo "IP pública: no se pudo obtener (sin red)"
  exit 1
fi

echo "IP pública actual: ${CURRENT_IP}"
echo "Añádela en Binance → API → Restricciones IP si no está."

if [[ -f "${LAST_IP_FILE}" ]]; then
  LAST_IP="$(cat "${LAST_IP_FILE}")"
  if [[ "${LAST_IP}" != "${CURRENT_IP}" ]]; then
    echo "⚠ IP cambió: ${LAST_IP} → ${CURRENT_IP}"
    echo "  Actualiza la whitelist de Binance o el bot no podrá operar."
  fi
fi

echo "${CURRENT_IP}" > "${LAST_IP_FILE}"
