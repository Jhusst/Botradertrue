from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import get_settings
from trading_bot.core.exceptions import KillSwitchEngagedError, LiveModeBlockedError
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.broker.binance_broker import BinanceBroker, BrokerOrderResult
from trading_bot.features.broker.execution_service import ExecutionOutcome, OrderExecutionService


class ExecutionEngine:
    """Motor de ejecución real — requiere candados explícitos en .env."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.broker = BinanceBroker(self.settings)

    async def execute_protected(
        self,
        *,
        session: AsyncSession,
        trade: UserTrade,
        position_size_usdt: Decimal,
        leverage: int,
    ) -> ExecutionOutcome:
        """Apertura idempotente con SL garantizado (vía OrderExecutionService)."""
        can, reason = self.broker.can_execute()
        if not can:
            raise LiveModeBlockedError(reason)

        from trading_bot.db.init_db import ensure_bot_state

        state = await ensure_bot_state(session)
        if state.kill_switch_engaged or state.entries_paused:
            raise KillSwitchEngagedError(
                state.kill_switch_reason or state.pause_reason or "Entradas pausadas"
            )

        service = OrderExecutionService(session, self.settings, broker=self.broker)
        return await service.open_protected_position(
            trade=trade, position_size_usdt=position_size_usdt, leverage=leverage
        )

    def execute(
        self,
        *,
        symbol: str,
        direction: str,
        entry_price: Decimal,
        position_size_usdt: Decimal,
        leverage: int,
        stop_loss: Decimal | None = None,
        take_profit_1: Decimal | None = None,
    ) -> BrokerOrderResult:
        """Camino legado sin idempotencia — usar execute_protected en su lugar."""
        can, reason = self.broker.can_execute()
        if not can:
            raise LiveModeBlockedError(reason)

        return self.broker.open_position(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            position_size_usdt=position_size_usdt,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
        )

    def can_execute_live(self, paper_stats: dict, backtest_passed: bool) -> tuple[bool, str]:
        if not self.settings.live_mode_enabled:
            return False, "LIVE_MODE_ENABLED=false en configuración."

        if not backtest_passed:
            return False, "Backtest no pasó validación mínima."

        total = paper_stats.get("total_closed", 0)
        if total < self.settings.min_paper_trades_for_live:
            return False, f"Solo {total}/{self.settings.min_paper_trades_for_live} operaciones en paper."

        pf = paper_stats.get("profit_factor", 0)
        if pf < self.settings.min_profit_factor_for_live:
            return False, f"Profit factor paper ({pf}) < {self.settings.min_profit_factor_for_live}."

        return False, "Requiere confirmación manual del usuario en dashboard/API."
