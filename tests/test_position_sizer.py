from decimal import Decimal

import pytest

from trading_bot.core.enums import SetupGrade, TradeDirection
from trading_bot.modules.position_sizer import PositionSizer
from trading_bot.schemas.risk import PositionSizingInput


@pytest.fixture
def sizer() -> PositionSizer:
    return PositionSizer()


@pytest.fixture
def long_input() -> PositionSizingInput:
    return PositionSizingInput(
        balance_usdt=Decimal("10000"),
        risk_percent=Decimal("0.5"),
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("51000"),
        take_profit_2=Decimal("52000"),
        direction=TradeDirection.LONG,
        setup_grade=SetupGrade.A,
        primary_timeframe="1h",
        atr_percent=Decimal("1.5"),
    )


def test_calculates_position_size(sizer: PositionSizer, long_input: PositionSizingInput) -> None:
    result = sizer.calculate(long_input)
    assert result.risk_usdt == Decimal("50.00")
    assert result.position_size_usdt == Decimal("2500.00")
    assert result.risk_reward_ratio == Decimal("2.00")
    assert result.recommended_leverage >= 1


def test_liquidation_long(sizer: PositionSizer, long_input: PositionSizingInput) -> None:
    result = sizer.calculate(long_input)
    assert result.liquidation_price is not None
    assert result.liquidation_price < long_input.entry_price


def test_higher_volatility_lower_leverage(sizer: PositionSizer, long_input: PositionSizingInput) -> None:
    low_vol = sizer.calculate(long_input)
    long_input.atr_percent = Decimal("5")
    high_vol = sizer.calculate(long_input)
    assert high_vol.recommended_leverage <= low_vol.recommended_leverage


def test_zero_stop_raises(sizer: PositionSizer, long_input: PositionSizingInput) -> None:
    long_input.stop_loss = long_input.entry_price
    with pytest.raises(ValueError):
        sizer.calculate(long_input)
