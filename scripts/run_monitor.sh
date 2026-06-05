#!/usr/bin/env bash
# Ejecuta solo el monitor en foreground (sin API completa)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH=src
export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./trading_bot.db}"

"${ROOT}/.venv/bin/python" -c "
import asyncio
from trading_bot.config.settings import get_settings
from trading_bot.db.init_db import create_tables
from trading_bot.db.session import engine, async_session_factory
from trading_bot.modules.signal_monitor.service import SignalMonitorService

async def main():
    await create_tables(engine)
    s = get_settings()
    monitor = SignalMonitorService(async_session_factory, s)
    monitor.start()
    print('Monitor activo. Símbolos:', monitor.watch_symbols)
    print('Telegram:', 'OK' if monitor.notifier.is_configured else 'NO CONFIGURADO')
    while monitor.is_running:
        r = await monitor.run_cycle()
        print('Ciclo:', r)
        await asyncio.sleep(s.price_check_interval_seconds)

asyncio.run(main())
"
