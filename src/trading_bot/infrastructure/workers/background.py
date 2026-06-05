import asyncio
import contextlib

import structlog

from trading_bot.config.settings import get_settings
from trading_bot.db.session import async_session_factory
from trading_bot.features.signals.monitor.service import SignalMonitorService

logger = structlog.get_logger()
_monitor: SignalMonitorService | None = None
_task: asyncio.Task | None = None


def get_monitor() -> SignalMonitorService:
    global _monitor
    if _monitor is None:
        _monitor = SignalMonitorService(async_session_factory, get_settings())
    return _monitor


async def _monitor_loop() -> None:
    settings = get_settings()
    monitor = get_monitor()
    monitor.start()
    logger.info("monitor_started", symbols=monitor.watch_symbols)
    while monitor.is_running:
        try:
            result = await monitor.run_cycle()
            logger.info("monitor_cycle", **result)
        except Exception as exc:
            logger.error("monitor_cycle_error", error=str(exc))
        await asyncio.sleep(settings.price_check_interval_seconds)


async def start_background_monitor() -> None:
    global _task
    settings = get_settings()
    if not settings.monitor_enabled:
        return
    monitor = get_monitor()
    if _task and not _task.done():
        return
    monitor.start()
    _task = asyncio.create_task(_monitor_loop())


async def stop_background_monitor() -> None:
    global _task
    monitor = get_monitor()
    monitor.stop()
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
    logger.info("monitor_stopped")
