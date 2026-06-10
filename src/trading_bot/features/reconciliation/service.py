"""Reconciliación periódica DB ↔ Binance.

La fuente de verdad es el exchange: la DB se corrige contra él, nunca al revés.

Casos:
  A) Trade OPEN en DB sin posición en exchange → cerrar con PnL real (fetch_my_trades)
  B) Posición en exchange sin trade en DB → alertar (o flatten si ADOPT_UNKNOWN_POSITIONS)
  C) Trade OPEN con posición pero sin orden SL activa → reponer SL (o flatten)
  E) Órdenes abiertas de un símbolo sin posición ni trade → cancelar huérfanas
Además evalúa el piso de equity (límite de pérdida absoluto en USDT).
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
from trading_bot.db.models.account import Account
from trading_bot.db.models.broker_order import BrokerOrder
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.broker.execution_service import OrderExecutionService
from trading_bot.infrastructure.audit.logger import AuditLogger

logger = structlog.get_logger()


@dataclass
class ReconcileReport:
    fixed: int = 0
    alerts: int = 0
    closed_trades: list[int] = field(default_factory=list)
    sl_restored: list[int] = field(default_factory=list)
    orphan_orders_cancelled: list[str] = field(default_factory=list)
    equity: Decimal | None = None
    kill_switch_triggered: bool = False


class ReconciliationService:
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
        self.execution = OrderExecutionService(
            session, self.settings, broker=self.broker, notifier=self.notifier
        )

    async def run(self) -> ReconcileReport:
        report = ReconcileReport()
        if not self.broker.is_configured():
            return report

        try:
            positions = await asyncio.to_thread(self.broker.fetch_positions_safe)
            open_orders = await asyncio.to_thread(self.broker.fetch_open_orders_safe)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile_fetch_failed", error=str(exc))
            return report

        result = await self.session.execute(select(UserTrade).where(UserTrade.status == "OPEN"))
        open_trades = [t for t in result.scalars().all() if self._is_broker_trade_sync(t)]

        positions_by_symbol = {p.get("symbol"): p for p in positions}
        trades_by_symbol: dict[str, list[UserTrade]] = {}
        for trade in open_trades:
            resolved = self.broker.resolve_futures_symbol(trade.symbol)
            trades_by_symbol.setdefault(resolved, []).append(trade)

        # Caso A: trade abierto en DB, sin posición en exchange → cerrar con PnL real
        for resolved, trades in trades_by_symbol.items():
            if resolved in positions_by_symbol:
                continue
            for trade in trades:
                await self._close_with_real_pnl(trade, report)

        # Caso B: posición en exchange sin trade en DB
        for resolved, pos in positions_by_symbol.items():
            if resolved in trades_by_symbol:
                continue
            await self._handle_unknown_position(resolved, pos, report)

        # Caso C: posición existe pero sin SL activa
        sl_order_symbols = {
            o.get("symbol")
            for o in open_orders
            if (o.get("type") or "").lower() in ("stop_market", "stop")
        }
        for resolved, trades in trades_by_symbol.items():
            if resolved not in positions_by_symbol or resolved in sl_order_symbols:
                continue
            for trade in trades:
                restored = await self.execution.ensure_stop_loss(trade)
                if restored:
                    report.sl_restored.append(trade.id)
                    report.fixed += 1
                    AuditLogger.log(
                        "reconcile", AuditAction.RECONCILE_FIX,
                        f"SL repuesto para {trade.symbol}", entity_id=trade.id,
                    )
                else:
                    await self.execution.flatten_trade(trade, "SL_MISSING_ON_RECONCILE")
                    report.fixed += 1

        # Caso E: órdenes huérfanas (símbolo sin posición ni trade abierto)
        orphan_symbols = {
            o.get("symbol")
            for o in open_orders
            if o.get("symbol") not in positions_by_symbol and o.get("symbol") not in trades_by_symbol
        }
        for symbol in orphan_symbols:
            if not symbol:
                continue
            try:
                await asyncio.to_thread(self.broker.cancel_all_orders, symbol)
                report.orphan_orders_cancelled.append(symbol)
                report.fixed += 1
                AuditLogger.log(
                    "reconcile", AuditAction.RECONCILE_FIX, f"Órdenes huérfanas canceladas {symbol}"
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("reconcile_cancel_orphans_failed", symbol=symbol, error=str(exc))

        # Piso de equity: límite de pérdida absoluto
        await self._check_equity_floor(report)

        await self.session.commit()
        return report

    def _is_broker_trade_sync(self, trade: UserTrade) -> bool:
        """Solo reconciliamos trades que tienen órdenes reales en el broker."""
        return "Binance" in (trade.notes or "")

    async def _has_broker_entry(self, trade: UserTrade) -> bool:
        result = await self.session.execute(
            select(BrokerOrder).where(
                BrokerOrder.user_trade_id == trade.id,
                BrokerOrder.kind == BrokerOrder.KIND_ENTRY,
                BrokerOrder.status.in_([BrokerOrder.STATUS_ACKED, BrokerOrder.STATUS_FILLED]),
            )
        )
        return result.scalar_one_or_none() is not None

    async def _close_with_real_pnl(self, trade: UserTrade, report: ReconcileReport) -> None:
        opened = trade.opened_at or trade.created_at
        if opened is not None and opened.tzinfo is None:
            opened = opened.replace(tzinfo=UTC)
        since_ms = int(opened.timestamp() * 1000) if opened else 0

        exit_price: Decimal | None = None
        realized = Decimal("0")
        close_reason = "EXCHANGE_CLOSED"
        try:
            fills = await asyncio.to_thread(self.broker.fetch_my_trades_since, trade.symbol, since_ms)
            sl_coid = self.execution.client_order_id(trade.id, BrokerOrder.KIND_SL)
            tp_coid = self.execution.client_order_id(trade.id, BrokerOrder.KIND_TP)
            reduce_fills = []
            for fill in fills:
                info = fill.get("info", {}) or {}
                pnl = info.get("realizedPnl")
                if pnl is not None and Decimal(str(pnl)) != 0:
                    reduce_fills.append(fill)
                    realized += Decimal(str(pnl))
                coid = str(info.get("clientOrderId") or "")
                if coid == sl_coid:
                    close_reason = "STOP_LOSS"
                elif coid == tp_coid:
                    close_reason = "TAKE_PROFIT"
            if reduce_fills:
                last = reduce_fills[-1]
                if last.get("price") is not None:
                    exit_price = Decimal(str(last["price"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile_pnl_fetch_failed", trade_id=trade.id, error=str(exc))

        trade.status = "CLOSED"
        trade.exit_price = exit_price
        trade.pnl_usdt = realized if realized != 0 else trade.pnl_usdt
        trade.close_reason = close_reason
        trade.closed_at = datetime.now(UTC)

        acc_result = await self.session.execute(select(Account).where(Account.id == trade.account_id))
        account = acc_result.scalar_one_or_none()
        if account is not None and realized != 0:
            account.balance_usdt += realized
            account.daily_pnl_usdt += realized
            account.weekly_pnl_usdt += realized
            if realized < 0:
                account.consecutive_losses += 1
            else:
                account.consecutive_losses = 0

        try:
            await asyncio.to_thread(self.broker.cancel_all_orders, trade.symbol)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile_cancel_failed", symbol=trade.symbol, error=str(exc))

        report.closed_trades.append(trade.id)
        report.fixed += 1
        AuditLogger.log(
            "reconcile", AuditAction.RECONCILE_FIX,
            f"Trade {trade.id} cerrado por exchange: {close_reason} PnL {realized}",
            entity_id=trade.id,
        )
        if self.notifier.is_configured:
            await self.notifier.send_alert(
                AlertType.STOP_LOSS if close_reason == "STOP_LOSS" else AlertType.TAKE_PROFIT,
                symbol=trade.symbol,
                direction=trade.direction,
                extra=f"Cierre confirmado en Binance ({close_reason}). PnL real: ${realized} USDT",
            )

    async def _handle_unknown_position(self, symbol: str, pos: dict, report: ReconcileReport) -> None:
        report.alerts += 1
        AuditLogger.log(
            "reconcile", AuditAction.RECONCILE_ALERT,
            f"Posición desconocida en exchange: {symbol} {pos.get('side')} {pos.get('contracts')}",
        )
        if self.settings.adopt_unknown_positions:
            try:
                await asyncio.to_thread(
                    self.broker.cancel_all_orders, symbol
                )
                coid = f"{self.settings.client_order_prefix}-unk-{symbol.replace('/', '').replace(':', '')[:20]}"
                await asyncio.to_thread(
                    self.broker.close_position_market, symbol, client_order_id=coid
                )
                report.fixed += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("reconcile_flatten_unknown_failed", symbol=symbol, error=str(exc))
        if self.notifier.is_configured:
            await self.notifier.send_alert(
                AlertType.RECONCILE_MISMATCH,
                symbol=symbol,
                direction=str(pos.get("side", "?")).upper(),
                extra=(
                    f"Posición en Binance sin trade en DB ({pos.get('contracts')} contratos). "
                    + ("Aplanada automáticamente." if self.settings.adopt_unknown_positions
                       else "Revisa manualmente (ADOPT_UNKNOWN_POSITIONS=false).")
                ),
            )

    async def _check_equity_floor(self, report: ReconcileReport) -> None:
        try:
            equity = await asyncio.to_thread(self.broker.fetch_equity)
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile_equity_fetch_failed", error=str(exc))
            return
        report.equity = equity

        floor = max(
            Decimal(str(self.settings.min_equity_usdt)),
            Decimal(str(self.settings.initial_equity_usdt))
            - Decimal(str(self.settings.max_total_loss_usdt)),
        )
        if equity > floor:
            return

        from trading_bot.db.init_db import ensure_bot_state

        state = await ensure_bot_state(self.session)
        if state.equity_floor_breached_at is not None:
            return  # ya disparado: no repetir flatten en cada ciclo

        state.equity_floor_breached_at = datetime.now(UTC)
        await self.session.commit()

        from trading_bot.features.safety.service import SafetyService

        safety = SafetyService(
            self.session, self.settings, broker=self.broker, notifier=self.notifier
        )
        await safety.engage_kill_switch(
            f"Equity {equity} USDT <= piso {floor} USDT", flatten=True, by="equity_floor"
        )
        report.kill_switch_triggered = True
