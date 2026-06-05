#!/usr/bin/env bash
# Servidor Ollama local para el filtro IA del bot (sin sudo).
set -euo pipefail

OLLAMA_ROOT="${HOME}/.local/share/ollama"
OLLAMA_BIN="${OLLAMA_ROOT}/bin/ollama"
if [[ ! -x "${OLLAMA_BIN}" ]]; then
  echo "Ollama no instalado en ${OLLAMA_ROOT}"
  echo "Instala con: curl -fsSL https://ollama.com/download/ollama-linux-amd64.tar.zst | tar -I unzstd -xf - -C /tmp && cp -r /tmp/bin /tmp/lib ${OLLAMA_ROOT}/"
  echo "O con sudo: pacman -S ollama"
  exit 1
fi

export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export PATH="${OLLAMA_ROOT}/bin:${PATH}"
echo "Ollama en http://${OLLAMA_HOST}"
echo "Modelo en .env: OLLAMA_MODEL (qwen2.5:7b recomendado)"
exec "${OLLAMA_BIN}" serve
