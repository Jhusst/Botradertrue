from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.core.enums import TradeDirection
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.signal_outcome import SignalOutcome
from trading_bot.db.models.user_trade import UserTrade

OUTCOME_LABELS = {
    "PENDING": "En seguimiento",
    "TP2": "Tocó TP2 (ganadora)",
    "TP1": "Tocó TP1 (parcial)",
    "STOP_LOSS": "Tocó SL (perdedora)",
    "INVALIDATED": "Invalidada antes de entrada",
    "NO_ENTRY": "Caducó sin tocar TP ni SL",
    "EXPIRED_OPEN": "Caducó tras entrada sin TP/SL",
    "EXECUTED": "Ejecutada en broker",
}

RESOLVED_OUTCOMES = frozenset(
    {"TP2", "TP1", "STOP_LOSS", "INVALIDATED", "NO_ENTRY", "EXPIRED_OPEN", "EXECUTED"}
)

SKIP_NOT_EXECUTED = "NOT_EXECUTED"


class SignalOutcomeTracker:
    """Registra TODAS las señales operables y mide si el precio tocó TP o SL."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def has_trade(self, signal_id: int) -> bool:
        result = await self.session.execute(
            select(UserTrade.id).where(UserTrade.signal_id == signal_id).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def get_or_create(self, signal: Signal) -> SignalOutcome:
        result = await self.session.execute(
            select(SignalOutcome).where(SignalOutcome.signal_id == signal.id)
        )
        row = result.scalar_one_or_none()
        if row:
            return row
        row = SignalOutcome(
            signal_id=signal.id,
            symbol=signal.symbol,
            direction=signal.direction,
            setup_grade=signal.setup_grade,
            executed=False,
            skip_reason=SKIP_NOT_EXECUTED,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    async def register_new_signal(self, signal: Signal) -> SignalOutcome:
        """Toda señal operable entra al histórico desde que se crea."""
        return await self.get_or_create(signal)

    async def mark_executed(self, signal: Signal) -> None:
        row = await self.get_or_create(signal)
        row.executed = True
        row.outcome = "EXECUTED"
        row.outcome_label = OUTCOME_LABELS["EXECUTED"]
        row.resolved_at = datetime.now(UTC)
        row.skip_reason = None

    async def register_skip(self, signal: Signal, *, reason: str, entry_touched: bool) -> None:
        if await self.has_trade(signal.id):
            await self.mark_executed(signal)
            return
        row = await self.get_or_create(signal)
        row.executed = False
        row.skip_reason = reason
        row.entry_touched = entry_touched or row.entry_touched

    def _update_price_range(self, row: SignalOutcome, price: Decimal) -> None:
        if row.min_price_seen is None or price < row.min_price_seen:
            row.min_price_seen = price
        if row.max_price_seen is None or price > row.max_price_seen:
            row.max_price_seen = price

    async def track_price(self, signal: Signal, price: Decimal, *, entry_touched: bool | None = None) -> str | None:
        if await self.has_trade(signal.id):
            await self.mark_executed(signal)
            return "EXECUTED"

        row = await self.get_or_create(signal)
        if row.outcome in RESOLVED_OUTCOMES:
            return row.outcome

        if entry_touched is not None:
            row.entry_touched = entry_touched or row.entry_touched

        self._update_price_range(row, price)
        hit = self._check_range(signal, row.min_price_seen, row.max_price_seen)
        if hit:
            self._resolve_row(row, hit, price)
            return hit
        return None

    async def resolve_expired(self, signal: Signal, price: Decimal) -> SignalOutcome:
        if await self.has_trade(signal.id):
            await self.mark_executed(signal)
            result = await self.session.execute(
                select(SignalOutcome).where(SignalOutcome.signal_id == signal.id)
            )
            return result.scalar_one()

        row = await self.get_or_create(signal)
        if row.outcome in RESOLVED_OUTCOMES:
            return row

        self._update_price_range(row, price)

        hit = self._check_range(signal, row.min_price_seen, row.max_price_seen)
        if hit:
            self._resolve_row(row, hit, price)
            return row

        if not row.entry_touched:
            row.outcome = "NO_ENTRY"
            row.outcome_label = OUTCOME_LABELS["NO_ENTRY"]
        else:
            row.outcome = "EXPIRED_OPEN"
            row.outcome_label = OUTCOME_LABELS["EXPIRED_OPEN"]
        if not row.skip_reason or row.skip_reason == SKIP_NOT_EXECUTED:
            row.skip_reason = "EXPIRED"
        row.exit_price = price
        row.resolved_at = datetime.now(UTC)
        return row

    async def resolve_invalidated(self, signal: Signal, price: Decimal) -> SignalOutcome:
        row = await self.get_or_create(signal)
        row.executed = False
        row.skip_reason = "INVALIDATED"
        row.entry_touched = False
        self._update_price_range(row, price)
        row.outcome = "INVALIDATED"
        row.outcome_label = OUTCOME_LABELS["INVALIDATED"]
        row.exit_price = price
        row.resolved_at = datetime.now(UTC)
        return row

    async def finalize_untracked_signals(self, price_feed) -> int:
        """Cierra señales ya caducadas/invalidadas que aún no tienen outcome."""
        from trading_bot.core.enums import SignalStatus

        terminal = [
            SignalStatus.EXPIRED.value,
            SignalStatus.INVALIDATED.value,
            SignalStatus.CLOSED.value,
        ]
        result = await self.session.execute(
            select(Signal).where(
                Signal.should_trade.is_(True),
                Signal.status.in_(terminal),
            )
        )
        signals = result.scalars().all()
        count = 0
        for signal in signals:
            existing = await self.session.execute(
                select(SignalOutcome).where(SignalOutcome.signal_id == signal.id)
            )
            row = existing.scalar_one_or_none()
            if row and row.outcome in RESOLVED_OUTCOMES:
                continue
            try:
                price = price_feed.get_price(signal.symbol)
            except Exception:
                price = signal.last_price or signal.entry_price
            if price is None:
                continue
            if signal.status == SignalStatus.INVALIDATED.value:
                await self.resolve_invalidated(signal, price)
            else:
                await self.resolve_expired(signal, price)
            count += 1
        return count

    def _resolve_row(self, row: SignalOutcome, outcome: str, price: Decimal) -> None:
        row.outcome = outcome
        row.outcome_label = OUTCOME_LABELS.get(outcome, outcome)
        row.exit_price = price
        row.resolved_at = datetime.now(UTC)

    @staticmethod
    def classify_skip_reason(blocked_reason: str) -> str:
        lower = blocked_reason.lower()
        if "ia bloqueó" in lower or "ai" in lower:
            return "AI_BLOCKED"
        if "binance" in lower or "broker" in lower:
            return "BROKER_BLOCKED"
        if "balance" in lower or "capital" in lower or "mínimo" in lower:
            return "CAPITAL"
        return "BLOCKED"

    @staticmethod
    def _check_range(
        signal: Signal,
        min_price: Decimal | None,
        max_price: Decimal | None,
    ) -> str | None:
        if not signal.stop_loss or min_price is None or max_price is None:
            return None
        direction = signal.direction
        if direction == TradeDirection.LONG.value:
            if min_price <= signal.stop_loss:
                return "STOP_LOSS"
            if signal.take_profit_2 and max_price >= signal.take_profit_2:
                return "TP2"
            if signal.take_profit_1 and max_price >= signal.take_profit_1:
                return "TP1"
        elif direction == TradeDirection.SHORT.value:
            if max_price >= signal.stop_loss:
                return "STOP_LOSS"
            if signal.take_profit_2 and min_price <= signal.take_profit_2:
                return "TP2"
            if signal.take_profit_1 and min_price <= signal.take_profit_1:
                return "TP1"
        return None
