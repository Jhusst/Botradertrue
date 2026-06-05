from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.core.enums import PaperTradeStatus, TradeDirection
from trading_bot.schemas.signal import SignalCreate


@dataclass
class PaperTradeRecord:
    id: int
    signal_id: int
    symbol: str
    direction: TradeDirection
    status: PaperTradeStatus
    entry_price: Decimal
    stop_loss: Decimal
    take_profit_1: Decimal
    take_profit_2: Decimal
    position_size: Decimal
    leverage: int
    margin_used: Decimal
    risk_usdt: Decimal
    pnl_usdt: Decimal | None = None
    close_reason: str | None = None


class PaperTradingSimulator:
    """Simula ejecución de señales sin conectar a exchange real."""

    def __init__(self) -> None:
        self._trade_counter = 0
        self._open_trades: dict[int, PaperTradeRecord] = {}

    def open_from_signal(self, signal_id: int, signal: SignalCreate) -> PaperTradeRecord | None:
        if not signal.should_trade or signal.direction == TradeDirection.NO_TRADE:
            return None
        if not all([signal.entry_price, signal.stop_loss, signal.take_profit_1, signal.take_profit_2]):
            return None

        self._trade_counter += 1
        trade = PaperTradeRecord(
            id=self._trade_counter,
            signal_id=signal_id,
            symbol=signal.symbol,
            direction=signal.direction,
            status=PaperTradeStatus.PENDING,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            position_size=signal.position_size or Decimal("0"),
            leverage=signal.recommended_leverage or 1,
            margin_used=signal.margin_required or Decimal("0"),
            risk_usdt=signal.risk_usdt or Decimal("0"),
        )
        self._open_trades[trade.id] = trade
        return trade

    def update_with_price(self, trade_id: int, current_price: Decimal) -> PaperTradeRecord | None:
        trade = self._open_trades.get(trade_id)
        if not trade:
            return None

        if trade.status == PaperTradeStatus.PENDING:
            if self._price_touched_entry(trade, current_price):
                trade.status = PaperTradeStatus.OPEN
            return trade

        if trade.status == PaperTradeStatus.OPEN:
            if self._hit_stop(trade, current_price):
                trade.status = PaperTradeStatus.STOPPED
                trade.pnl_usdt = -trade.risk_usdt
                trade.close_reason = "STOP_LOSS"
            elif self._hit_tp2(trade, current_price):
                trade.status = PaperTradeStatus.CLOSED
                trade.pnl_usdt = self._calc_pnl(trade, trade.take_profit_2)
                trade.close_reason = "TAKE_PROFIT_2"
            elif self._hit_tp1(trade, current_price):
                trade.status = PaperTradeStatus.TP1_HIT
            return trade

        if trade.status == PaperTradeStatus.TP1_HIT:
            if self._hit_stop(trade, current_price):
                trade.status = PaperTradeStatus.CLOSED
                trade.pnl_usdt = trade.risk_usdt * Decimal("0.5")
                trade.close_reason = "BREAK_EVEN_AFTER_TP1"
            elif self._hit_tp2(trade, current_price):
                trade.status = PaperTradeStatus.CLOSED
                trade.pnl_usdt = self._calc_pnl(trade, trade.take_profit_2)
                trade.close_reason = "TAKE_PROFIT_2"
            return trade

        return trade

    def get_stats(self) -> dict:
        closed = [t for t in self._open_trades.values() if t.pnl_usdt is not None]
        total = len(closed)
        wins = [t for t in closed if t.pnl_usdt and t.pnl_usdt > 0]
        losses = [t for t in closed if t.pnl_usdt and t.pnl_usdt <= 0]
        gross_profit = sum(t.pnl_usdt for t in wins if t.pnl_usdt)
        gross_loss = sum(abs(t.pnl_usdt) for t in losses if t.pnl_usdt)
        pf = float(gross_profit / gross_loss) if gross_loss else 0
        return {
            "total_closed": total,
            "wins": len(wins),
            "losses": len(losses),
            "profit_factor": round(pf, 4),
            "ready_for_live": total >= 100 and pf >= 1.3,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def _price_touched_entry(trade: PaperTradeRecord, price: Decimal) -> bool:
        if trade.direction == TradeDirection.LONG:
            return price <= trade.entry_price
        return price >= trade.entry_price

    @staticmethod
    def _hit_stop(trade: PaperTradeRecord, price: Decimal) -> bool:
        if trade.direction == TradeDirection.LONG:
            return price <= trade.stop_loss
        return price >= trade.stop_loss

    @staticmethod
    def _hit_tp1(trade: PaperTradeRecord, price: Decimal) -> bool:
        if trade.direction == TradeDirection.LONG:
            return price >= trade.take_profit_1
        return price <= trade.take_profit_1

    @staticmethod
    def _hit_tp2(trade: PaperTradeRecord, price: Decimal) -> bool:
        if trade.direction == TradeDirection.LONG:
            return price >= trade.take_profit_2
        return price <= trade.take_profit_2

    @staticmethod
    def _calc_pnl(trade: PaperTradeRecord, exit_price: Decimal) -> Decimal:
        diff = exit_price - trade.entry_price
        if trade.direction == TradeDirection.SHORT:
            diff = -diff
        return (trade.position_size * diff / trade.entry_price).quantize(Decimal("0.01"))
