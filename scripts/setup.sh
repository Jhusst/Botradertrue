#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${ROOT}/.venv/bin/python"
PIP="${ROOT}/.venv/bin/pip"

if [ ! -d ".venv" ]; then
  python -m venv .venv
fi

"$PIP" install --upgrade pip
"$PIP" install -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "Creado .env desde .env.example"
fi

echo ""
echo "Setup listo."
echo ""
echo "Para iniciar (funciona en bash, zsh y fish):"
echo "  ./scripts/run_api.sh"
echo ""
echo "Si usas fish y quieres activar el venv manualmente:"
echo "  source .venv/bin/activate.fish"
