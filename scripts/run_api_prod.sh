#!/usr/bin/env bash
# API sin --reload (producción / segundo plano).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH=src
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./trading_bot.db}"

exec "${ROOT}/.venv/bin/uvicorn" trading_bot.main:app --host 0.0.0.0 --port 8000
