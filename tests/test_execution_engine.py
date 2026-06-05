from decimal import Decimal

import pytest

from trading_bot.core.exceptions import LiveModeBlockedError
from trading_bot.modules.execution_engine.engine import ExecutionEngine


def test_execute_raises_blocked() -> None:
    engine = ExecutionEngine()
    with pytest.raises(LiveModeBlockedError):
        engine.execute(
            symbol="BTC/USDT",
            direction="LONG",
            entry_price=Decimal("50000"),
            position_size_usdt=Decimal("10"),
            leverage=5,
        )


def test_cannot_enable_live_without_requirements() -> None:
    engine = ExecutionEngine()
    can, reason = engine.can_execute_live({"total_closed": 10, "profit_factor": 0.5}, False)
    assert can is False
    assert reason
