from decimal import Decimal

from trading_bot.core.enums import TradeDirection
from trading_bot.modules.signal_generator.generator import SignalGenerator
from trading_bot.modules.strategy_engine.trend_pullback_mvp import MarketContext
from trading_bot.schemas.risk import AccountRiskState


def test_generate_returns_signal_with_symbol(sample_market_context, account_state) -> None:
    generator = SignalGenerator()
    signal = generator.generate(sample_market_context, account_state)
    assert signal.symbol == "BTC/USDT"
    assert signal.account_balance == Decimal("10000")


def test_no_trade_has_rejection_or_explanation(sample_market_context, account_state) -> None:
    generator = SignalGenerator()
    signal = generator.generate(sample_market_context, account_state)
    if signal.direction == TradeDirection.NO_TRADE:
        assert signal.should_trade is False
        assert signal.rejection_reason or signal.technical_explanation


def test_blocks_on_consecutive_losses() -> None:
    """El risk manager bloquea cuando hay 2+ pérdidas seguidas."""
    from trading_bot.core.enums import SetupGrade, TradeDirection
    from trading_bot.modules.risk_manager import RiskManager
    from trading_bot.schemas.risk import AccountRiskState, SetupCandidate

    account = AccountRiskState(balance_usdt=Decimal("10000"), consecutive_losses=2)
    setup = SetupCandidate(
        symbol="BTC/USDT",
        direction=TradeDirection.LONG,
        primary_timeframe="1h",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("51000"),
        take_profit_2=Decimal("52000"),
        setup_grade=SetupGrade.A,
        confidence_score=Decimal("85"),
        technical_explanation="Test",
        invalidation_conditions="SL",
    )
    result = RiskManager().assess(setup, account)
    assert result.approved is False
    assert "consecutivas" in (result.rejection_reason or "").lower()


def test_trade_signal_has_risk_fields(sample_market_context, account_state) -> None:
    signal = SignalGenerator().generate(sample_market_context, account_state)
    if signal.should_trade:
        assert signal.entry_price is not None
        assert signal.stop_loss is not None
        assert signal.risk_usdt is not None
        assert signal.recommended_leverage is not None
        assert signal.max_loss_usdt is not None
