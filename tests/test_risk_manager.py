from decimal import Decimal

import pytest

from trading_bot.core.enums import SetupGrade, TradeDirection
from trading_bot.modules.risk_manager import RiskManager
from trading_bot.schemas.risk import AccountRiskState, SetupCandidate


@pytest.fixture
def manager() -> RiskManager:
    return RiskManager()


@pytest.fixture
def good_setup() -> SetupCandidate:
    return SetupCandidate(
        symbol="BTC/USDT",
        direction=TradeDirection.LONG,
        primary_timeframe="1h",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("51000"),
        take_profit_2=Decimal("52000"),
        setup_grade=SetupGrade.A,
        confidence_score=Decimal("85"),
        technical_explanation="Tendencia alcista alineada.",
        invalidation_conditions="Ruptura de SL.",
    )


@pytest.fixture
def account() -> AccountRiskState:
    return AccountRiskState(balance_usdt=Decimal("10000"))


def test_approves_setup_a(manager: RiskManager, good_setup: SetupCandidate, account: AccountRiskState) -> None:
    result = manager.assess(good_setup, account)
    assert result.approved is True
    assert result.risk_percent == Decimal("1.0")
    assert result.risk_usdt == Decimal("100.00")


def test_rejects_low_rr(manager: RiskManager, good_setup: SetupCandidate, account: AccountRiskState) -> None:
    good_setup.take_profit_2 = Decimal("50500")
    result = manager.assess(good_setup, account)
    assert result.approved is False
    assert "riesgo/beneficio" in (result.rejection_reason or "").lower()


def test_blocks_consecutive_losses(manager: RiskManager, good_setup: SetupCandidate) -> None:
    account = AccountRiskState(balance_usdt=Decimal("10000"), consecutive_losses=2)
    result = manager.assess(good_setup, account)
    assert result.approved is False
    assert "consecutivas" in (result.rejection_reason or "").lower()


def test_blocks_daily_loss_limit(manager: RiskManager, good_setup: SetupCandidate) -> None:
    account = AccountRiskState(balance_usdt=Decimal("10000"), daily_pnl_usdt=Decimal("-200"))
    result = manager.assess(good_setup, account)
    assert result.approved is False


def test_setup_b_lower_risk(manager: RiskManager, good_setup: SetupCandidate) -> None:
    good_setup.setup_grade = SetupGrade.B
    account = AccountRiskState(
        balance_usdt=Decimal("10000"),
        min_setup_grade="B",
        risk_setup_b=Decimal("0.5"),
    )
    result = manager.assess(good_setup, account)
    assert result.approved is True
    assert result.risk_percent == Decimal("0.5")
