from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.core.enums import PaperTradeStatus, TradeDirection
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.trade import PaperTrade
from trading_bot.modules.paper_trading.simulator import PaperTradingSimulator
from trading_bot.schemas.signal import SignalCreate


class PaperTradingService:
    """Paper trading persistente en base de datos."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.simulator = PaperTradingSimulator()

    async def open_from_signal(self, signal: Signal) -> PaperTrade | None:
        if not signal.should_trade or signal.direction == TradeDirection.NO_TRADE.value:
            return None

        existing = await self.session.execute(
            select(PaperTrade).where(
                PaperTrade.signal_id == signal.id,
                PaperTrade.status.in_(
                    [PaperTradeStatus.PENDING.value, PaperTradeStatus.OPEN.value, PaperTradeStatus.TP1_HIT.value]
                ),
            )
        )
        if existing.scalar_one_or_none():
            return None

        signal_create = SignalCreate(
            symbol=signal.symbol,
            direction=TradeDirection(signal.direction),
            primary_timeframe=signal.primary_timeframe,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            risk_reward_ratio=signal.risk_reward_ratio,
            account_balance=signal.account_balance,
            risk_percent=signal.risk_percent,
            risk_usdt=signal.risk_usdt,
            recommended_capital_usdt=signal.recommended_capital_usdt,
            recommended_leverage=signal.recommended_leverage,
            max_loss_usdt=signal.max_loss_usdt,
            estimated_gain_tp1_usdt=signal.estimated_gain_tp1_usdt,
            estimated_gain_tp2_usdt=signal.estimated_gain_tp2_usdt,
            position_size=signal.position_size,
            margin_required=signal.margin_required,
            setup_grade=signal.setup_grade,
            confidence_score=signal.confidence_score,
            should_trade=True,
        )

        trade = PaperTrade(
            signal_id=signal.id,
            account_id=signal.account_id or 1,
            symbol=signal.symbol,
            direction=signal.direction,
            status=PaperTradeStatus.PENDING.value,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            position_size=signal.position_size or Decimal("0"),
            leverage=signal.recommended_leverage or 1,
            margin_used=signal.margin_required or Decimal("0"),
            risk_usdt=signal.risk_usdt or Decimal("0"),
        )
        self.session.add(trade)
        await self.session.flush()

        self.simulator.open_from_signal(trade.id, signal_create)
        trade.status = PaperTradeStatus.OPEN.value
        trade.opened_at = datetime.now(UTC)
        return trade

    async def update_open_trades(self, symbol: str, current_price: Decimal) -> list[tuple[PaperTrade, str | None]]:
        result = await self.session.execute(
            select(PaperTrade).where(
                PaperTrade.symbol == symbol,
                PaperTrade.status.in_(
                    [
                        PaperTradeStatus.PENDING.value,
                        PaperTradeStatus.OPEN.value,
                        PaperTradeStatus.TP1_HIT.value,
                    ]
                ),
            )
        )
        trades = result.scalars().all()
        events: list[tuple[PaperTrade, str | None]] = []

        for trade in trades:
            prev_status = trade.status
            sim_result = self.simulator.update_with_price(trade.id, current_price)
            if not sim_result:
                continue

            if sim_result.status == PaperTradeStatus.OPEN and prev_status == PaperTradeStatus.PENDING.value:
                trade.status = PaperTradeStatus.OPEN.value
                trade.opened_at = datetime.now(UTC)
                events.append((trade, "OPENED"))

            elif sim_result.status == PaperTradeStatus.TP1_HIT:
                trade.status = PaperTradeStatus.TP1_HIT.value
                events.append((trade, "TP1"))

            elif sim_result.status in (PaperTradeStatus.STOPPED, PaperTradeStatus.CLOSED):
                trade.status = PaperTradeStatus.CLOSED.value
                trade.closed_at = datetime.now(UTC)
                trade.exit_price = current_price
                trade.pnl_usdt = sim_result.pnl_usdt
                trade.close_reason = sim_result.close_reason
                event = "STOP_LOSS" if sim_result.close_reason == "STOP_LOSS" else "TAKE_PROFIT"
                events.append((trade, event))

        return events
