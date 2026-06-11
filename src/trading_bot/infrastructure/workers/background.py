import asyncio
import contextlib
from datetime import UTC, datetime

import structlog

from trading_bot.config.settings import get_settings
from trading_bot.core.enums import AlertType, AuditAction
from trading_bot.core.exceptions import CircuitOpenError
from trading_bot.db.session import async_session_factory
from trading_bot.features.signals.monitor.service import SignalMonitorService
from trading_bot.infrastructure.audit.logger import AuditLogger

logger = structlog.get_logger()
_monitor: SignalMonitorService | None = None
_task: asyncio.Task | None = None
_watchdog_task: asyncio.Task | None = None


def get_monitor() -> SignalMonitorService:
    global _monitor
    if _monitor is None:
        _monitor = SignalMonitorService(async_session_factory, get_settings())
    return _monitor


async def _write_heartbeat() -> None:
    from trading_bot.db.init_db import ensure_bot_state

    async with async_session_factory() as session:
        state = await ensure_bot_state(session)
        state.last_heartbeat_at = datetime.now(UTC)
        await session.commit()


async def _monitor_loop() -> None:
    settings = get_settings()
    monitor = get_monitor()
    monitor.start()
    logger.info("monitor_started", symbols=monitor.watch_symbols)
    consecutive_errors = 0
    while monitor.is_running:
        try:
            result = await asyncio.wait_for(
                monitor.run_cycle(), timeout=settings.monitor_cycle_timeout_seconds
            )
            logger.info("monitor_cycle", **result)
            consecutive_errors = 0
            try:
                await _write_heartbeat()
            except Exception as exc:  # noqa: BLE001 — heartbeat nunca tumba el loop
                logger.warning("heartbeat_write_failed", error=str(exc))
        except TimeoutError:
            consecutive_errors += 1
            logger.error(
                "monitor_cycle_timeout",
                timeout=settings.monitor_cycle_timeout_seconds,
                consecutive=consecutive_errors,
            )
        except CircuitOpenError as exc:
            logger.warning("monitor_circuit_open", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            consecutive_errors += 1
            logger.error("monitor_cycle_error", error=str(exc), consecutive=consecutive_errors)
        # Backoff suave si el ciclo falla repetido (sin superar 5x el intervalo)
        delay = settings.price_check_interval_seconds * min(1 + consecutive_errors, 5)
        await asyncio.sleep(delay)


async def _watchdog_loop() -> None:
    """Vigila el monitor: si el task murió o el heartbeat envejeció, lo reinicia."""
    global _task
    settings = get_settings()
    from trading_bot.db.init_db import ensure_bot_state
    from trading_bot.features.alerts.telegram import TelegramNotifier

    notifier = TelegramNotifier(settings)
    while True:
        await asyncio.sleep(settings.watchdog_interval_seconds)
        monitor = get_monitor()
        if not monitor.is_running:
            continue

        stale = False
        try:
            async with async_session_factory() as session:
                state = await ensure_bot_state(session)
                hb = state.last_heartbeat_at
                if hb is not None:
                    if hb.tzinfo is None:
                        hb = hb.replace(tzinfo=UTC)
                    age = (datetime.now(UTC) - hb).total_seconds()
                    stale = age > settings.watchdog_stale_after_seconds
        except Exception as exc:  # noqa: BLE001
            logger.warning("watchdog_heartbeat_read_failed", error=str(exc))

        crashed = _task is None or _task.done()
        if not crashed and not stale:
            continue

        reason = "task crashed" if crashed else "heartbeat stale"
        logger.error("watchdog_restarting_monitor", reason=reason)
        AuditLogger.log("watchdog", AuditAction.WATCHDOG_RESTART, f"Reiniciando monitor: {reason}")
        if _task and not _task.done():
            _task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await _task
        _task = asyncio.create_task(_monitor_loop())
        if notifier.is_configured:
            with contextlib.suppress(Exception):
                await notifier.send_alert(
                    AlertType.WATCHDOG_RESTART,
                    symbol="SYSTEM",
                    direction="-",
                    extra=f"Watchdog reinició el monitor ({reason}).",
                )


async def start_background_monitor() -> None:
    global _task, _watchdog_task
    settings = get_settings()
    if not settings.monitor_enabled:
        return
    monitor = get_monitor()
    if _task and not _task.done():
        return
    monitor.start()
    _task = asyncio.create_task(_monitor_loop())
    if _watchdog_task is None or _watchdog_task.done():
        _watchdog_task = asyncio.create_task(_watchdog_loop())


async def stop_background_monitor() -> None:
    global _task, _watchdog_task
    monitor = get_monitor()
    monitor.stop()
    for task_ref in ("_task", "_watchdog_task"):
        task = globals()[task_ref]
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            globals()[task_ref] = None
    logger.info("monitor_stopped")
