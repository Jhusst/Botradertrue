"""Kill-switch, pausa de entradas y flatten-all.

Todo estado se persiste en BotState (fila única) y sobrevive reinicios.
El rearme tras kill-switch es SOLO manual vía endpoint /safety/arm.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.enums import AlertType, AuditAction
from trading_bot.db.init_db import ensure_bot_state
from trading_bot.db.models.bot_state import BotState
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.infrastructure.audit.logger import AuditLogger

logger = structlog.get_logger()


@dataclass
class FlattenAllResult:
    ok: bool
    closed_symbols: list[str] = field(default_factory=list)
    failed_symbols: list[str] = field(default_factory=list)
    db_trades_closed: int = 0
    message: str = ""


@dataclass
class KillResult:
    engaged: bool
    flatten: FlattenAllResult | None = None
    message: str = ""


class SafetyService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        broker: BinanceBroker | None = None,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.broker = broker or BinanceBroker(self.settings)
        self.notifier = notifier or TelegramNotifier(self.settings)

    async def get_state(self) -> BotState:
        return await ensure_bot_state(self.session)

    async def pause_entries(self, reason: str, *, by: str) -> BotState:
        state = await self.get_state()
        state.entries_paused = True
        state.pause_reason = f"{reason} (por {by})"
        await self.session.commit()
        AuditLogger.log("safety", AuditAction.ENTRIES_PAUSED, f"{reason} (por {by})")
        return state

    async def resume_entries(self, *, by: str) -> BotState:
        """Reanuda entradas. NO rearma el kill-switch (eso requiere /safety/arm)."""
        state = await self.get_state()
        state.entries_paused = False
        state.pause_reason = None
        await self.session.commit()
        AuditLogger.log("safety", AuditAction.ENTRIES_RESUMED, f"Entradas reanudadas (por {by})")
        return state

    async def arm(self, *, by: str) -> BotState:
        """Rearma el sistema tras un kill-switch (solo manual, decisión explícita)."""
        state = await self.get_state()
        state.kill_switch_engaged = False
        state.kill_switch_reason = None
        state.entries_paused = False
        state.pause_reason = None
        state.equity_floor_breached_at = None
        await self.session.commit()
        AuditLogger.log("safety", AuditAction.KILL_SWITCH_ARMED, f"Sistema rearmado (por {by})")
        return state

    async def engage_kill_switch(
        self, reason: str, *, flatten: bool = True, by: str = "system"
    ) -> KillResult:
        state = await self.get_state()
        state.kill_switch_engaged = True
        state.entries_paused = True
        state.kill_switch_reason = f"{reason} (por {by})"
        await self.session.commit()
        AuditLogger.log("safety", AuditAction.KILL_SWITCH_ENGAGED, f"{reason} (por {by})")

        flatten_result: FlattenAllResult | None = None
        if flatten:
            flatten_result = await self.flatten_all(reason, by=by)

        if self.notifier.is_configured:
            extra = f"Motivo: {reason}"
            if flatten_result:
                extra += (
                    f" | Cerradas: {', '.join(flatten_result.closed_symbols) or 'ninguna'}"
                    + (f" | FALLARON: {', '.join(flatten_result.failed_symbols)}"
                       if flatten_result.failed_symbols else "")
                )
            try:
                await self.notifier.send_alert(
                    AlertType.KILL_SWITCH, symbol="SYSTEM", direction="-", extra=extra
                )
            except Exception:  # noqa: BLE001
                pass

        return KillResult(engaged=True, flatten=flatten_result, message=f"Kill-switch: {reason}")

    async def flatten_all(self, reason: str, *, by: str) -> FlattenAllResult:
        """Cierra TODAS las posiciones a mercado y cancela todas las órdenes."""
        result = FlattenAllResult(ok=True, message=reason)
        if not self.broker.is_configured():
            result.message = "Broker no configurado: solo se cierran trades en DB"
        else:
            try:
                positions = await asyncio.to_thread(self.broker.fetch_positions_safe)
            except Exception as exc:  # noqa: BLE001
                logger.error("flatten_all_fetch_failed", error=str(exc))
                positions = []
                result.ok = False
                result.message = f"No se pudieron leer posiciones: {exc}"

            stamp = datetime.now(UTC).strftime("%Y%m%d%H%M")
            for pos in positions:
                symbol = pos.get("symbol") or ""
                clean = symbol.replace("/", "").replace(":", "")[:16]
                coid = f"{self.settings.client_order_prefix}-flatall-{clean}-{stamp}"
                try:
                    await asyncio.to_thread(
                        self.broker.close_position_market, symbol, client_order_id=coid
                    )
                    await asyncio.to_thread(self.broker.cancel_all_orders, symbol)
                    result.closed_symbols.append(symbol)
                except Exception as exc:  # noqa: BLE001
                    logger.error("flatten_all_symbol_failed", symbol=symbol, error=str(exc))
                    result.failed_symbols.append(symbol)
                    result.ok = False

        # Cerrar trades OPEN en DB (el PnL exacto lo fija la reconciliación después)
        trades_result = await self.session.execute(
            select(UserTrade).where(UserTrade.status == "OPEN")
        )
        for trade in trades_result.scalars().all():
            trade.status = "CLOSED"
            trade.close_reason = f"FLATTEN_ALL:{reason}"[:50]
            trade.closed_at = datetime.now(UTC)
            result.db_trades_closed += 1
        await self.session.commit()

        AuditLogger.log(
            "safety", AuditAction.POSITION_FLATTENED,
            f"Flatten-all (por {by}): {len(result.closed_symbols)} posiciones, "
            f"{result.db_trades_closed} trades DB",
        )
        if self.notifier.is_configured:
            try:
                await self.notifier.send_alert(
                    AlertType.POSITION_FLATTENED,
                    symbol="ALL",
                    direction="-",
                    extra=(
                        f"Flatten-all por {by}. Cerradas: "
                        f"{', '.join(result.closed_symbols) or 'ninguna'}"
                        + (f" | FALLARON: {', '.join(result.failed_symbols)}"
                           if result.failed_symbols else "")
                    ),
                )
            except Exception:  # noqa: BLE001
                pass
        return result

    async def status_summary(self) -> dict:
        state = await self.get_state()
        equity: Decimal | None = None
        if self.broker.is_configured():
            try:
                equity = await asyncio.to_thread(self.broker.fetch_equity)
            except Exception:  # noqa: BLE001
                pass
        from trading_bot.infrastructure.resilience import exchange_breaker

        return {
            "entries_paused": state.entries_paused,
            "pause_reason": state.pause_reason,
            "kill_switch_engaged": state.kill_switch_engaged,
            "kill_switch_reason": state.kill_switch_reason,
            "equity_usdt": str(equity) if equity is not None else None,
            "equity_floor_usdt": str(
                max(
                    Decimal(str(self.settings.min_equity_usdt)),
                    Decimal(str(self.settings.initial_equity_usdt))
                    - Decimal(str(self.settings.max_total_loss_usdt)),
                )
            ),
            "circuit_breaker": exchange_breaker.state,
            "last_heartbeat_at": state.last_heartbeat_at.isoformat()
            if state.last_heartbeat_at
            else None,
        }
