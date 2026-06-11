#!/usr/bin/env bash
# Garantiza Ollama en 11434 (arranca en background si hace falta).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
URL="http://${HOST}/api/tags"

if curl -s --max-time 2 "${URL}" >/dev/null 2>&1; then
  echo "Ollama ya responde en ${URL}"
  exit 0
fi

nohup "${ROOT}/scripts/run_ollama.sh" >> "${ROOT}/logs/ollama.log" 2>&1 &
for _ in $(seq 1 30); do
  if curl -s --max-time 2 "${URL}" >/dev/null 2>&1; then
    echo "Ollama listo en ${URL}"
    exit 0
  fi
  sleep 1
done

echo "Ollama no respondió a tiempo" >&2
exit 1
