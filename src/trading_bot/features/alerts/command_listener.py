"""Comandos de emergencia por Telegram (long-poll getUpdates).

Solo acepta mensajes del chat_id configurado. Comandos:
  /status              → resumen de seguridad
  /pause               → pausar entradas nuevas
  /resume              → reanudar entradas
  /flatten CONFIRMAR   → cerrar TODO a mercado
  /kill CONFIRMAR      → kill-switch (flatten + bloquear; rearme solo por API)
  /close <trade_id>    → cierre manual de un trade

El rearme del kill-switch NUNCA está disponible por Telegram (anti-dedazo).
"""
from __future__ import annotations

import asyncio
import contextlib

import httpx
import structlog
from sqlalchemy.ext.asyncio import async_sessionmaker

from trading_bot.config.settings import Settings, get_settings
from trading_bot.db.init_db import ensure_bot_state

logger = structlog.get_logger()

_listener_task: asyncio.Task | None = None


class TelegramCommandListener:
    def __init__(self, session_factory: async_sessionmaker, settings: Settings | None = None) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self._running = False

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.telegram_bot_token
            and self.settings.telegram_chat_id
            and self.settings.telegram_commands_enabled
        )

    def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        if not self.is_configured:
            return
        self._running = True
        logger.info("telegram_commands_started")
        while self._running:
            try:
                await self._poll_once()
            except Exception as exc:  # noqa: BLE001 — el listener nunca tumba el proceso
                logger.warning("telegram_poll_error", error=str(exc))
                await asyncio.sleep(min(60, self.settings.telegram_command_poll_seconds * 4))
            await asyncio.sleep(self.settings.telegram_command_poll_seconds)

    async def _poll_once(self) -> None:
        async with self.session_factory() as session:
            state = await ensure_bot_state(session)
            offset = state.telegram_update_offset

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/getUpdates"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params={"offset": offset + 1, "timeout": 10})
            response.raise_for_status()
            updates = response.json().get("result", [])

        if not updates:
            return

        max_update_id = offset
        for update in updates:
            max_update_id = max(max_update_id, update.get("update_id", 0))
            message = update.get("message") or {}
            chat_id = str((message.get("chat") or {}).get("id", ""))
            text = (message.get("text") or "").strip()
            if chat_id != str(self.settings.telegram_chat_id):
                logger.warning("telegram_command_foreign_chat", chat_id=chat_id)
                continue
            if text.startswith("/"):
                await self._handle_command(text)

        async with self.session_factory() as session:
            state = await ensure_bot_state(session)
            state.telegram_update_offset = max_update_id
            await session.commit()

    async def _handle_command(self, text: str) -> None:
        from trading_bot.features.alerts.telegram import TelegramNotifier

        notifier = TelegramNotifier(self.settings)
        parts = text.split()
        command = parts[0].lower().split("@")[0]
        args = parts[1:]

        async with self.session_factory() as session:
            from trading_bot.features.safety.service import SafetyService

            safety = SafetyService(session, self.settings, notifier=notifier)

            if command == "/status":
                summary = await safety.status_summary()
                lines = [f"<b>{k}</b>: {v}" for k, v in summary.items()]
                await notifier.send_raw("📋 <b>STATUS</b>\n" + "\n".join(lines))
            elif command == "/pause":
                await safety.pause_entries("comando Telegram", by="telegram")
                await notifier.send_raw("⏸ Entradas pausadas.")
            elif command == "/resume":
                state = await safety.get_state()
                if state.kill_switch_engaged:
                    await notifier.send_raw(
                        "🛑 Kill-switch activado: el rearme solo es posible por API (/safety/arm)."
                    )
                else:
                    await safety.resume_entries(by="telegram")
                    await notifier.send_raw("▶️ Entradas reanudadas.")
            elif command == "/flatten":
                if args and args[0].upper() == "CONFIRMAR":
                    result = await safety.flatten_all("comando Telegram", by="telegram")
                    await notifier.send_raw(
                        f"🧯 Flatten-all: {len(result.closed_symbols)} posiciones cerradas, "
                        f"{result.db_trades_closed} trades DB."
                        + (f" FALLARON: {', '.join(result.failed_symbols)}"
                           if result.failed_symbols else "")
                    )
                else:
                    await notifier.send_raw("Para confirmar escribe: /flatten CONFIRMAR")
            elif command == "/kill":
                if args and args[0].upper() == "CONFIRMAR":
                    await safety.engage_kill_switch("comando Telegram", flatten=True, by="telegram")
                    await notifier.send_raw("🛑 Kill-switch activado. Rearme solo por API.")
                else:
                    await notifier.send_raw("Para confirmar escribe: /kill CONFIRMAR")
            elif command == "/close":
                if not args or not args[0].isdigit():
                    await notifier.send_raw("Uso: /close <trade_id>")
                else:
                    await self._close_trade(session, int(args[0]), notifier)
            else:
                await notifier.send_raw(
                    "Comandos: /status /pause /resume /flatten CONFIRMAR /kill CONFIRMAR /close <id>"
                )

    async def _close_trade(self, session, trade_id: int, notifier) -> None:
        from sqlalchemy import select

        from trading_bot.db.models.user_trade import UserTrade
        from trading_bot.features.broker.execution_service import OrderExecutionService

        result = await session.execute(select(UserTrade).where(UserTrade.id == trade_id))
        trade = result.scalar_one_or_none()
        if trade is None or trade.status != "OPEN":
            await notifier.send_raw(f"Trade #{trade_id} no encontrado o no está abierto.")
            return
        service = OrderExecutionService(session, self.settings, notifier=notifier)
        flatten = await service.flatten_trade(trade, "MANUAL_CLOSE")
        await notifier.send_raw(
            f"✋ Trade #{trade_id}: {'cerrado' if flatten.ok else 'FALLÓ — ' + flatten.message}"
        )


async def start_command_listener(session_factory: async_sessionmaker) -> None:
    global _listener_task
    settings = get_settings()
    listener = TelegramCommandListener(session_factory, settings)
    if not listener.is_configured:
        return
    if _listener_task and not _listener_task.done():
        return
    _listener_task = asyncio.create_task(listener.run())


async def stop_command_listener() -> None:
    global _listener_task
    if _listener_task:
        _listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _listener_task
        _listener_task = None
