from decimal import Decimal

from trading_bot.core.enums import PaperTradeStatus, SetupGrade, TradeDirection
from trading_bot.features.trades.paper.simulator import PaperTradingSimulator
from trading_bot.schemas.signal import SignalCreate


def _tradeable_signal() -> SignalCreate:
    return SignalCreate(
        symbol="BTC/USDT",
        direction=TradeDirection.LONG,
        primary_timeframe="1h",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("51000"),
        take_profit_2=Decimal("52000"),
        risk_reward_ratio=Decimal("2"),
        account_balance=Decimal("10000"),
        risk_percent=Decimal("0.5"),
        risk_usdt=Decimal("50"),
        recommended_capital_usdt=Decimal("500"),
        recommended_leverage=3,
        max_loss_usdt=Decimal("50"),
        estimated_gain_tp1_usdt=Decimal("50"),
        estimated_gain_tp2_usdt=Decimal("100"),
        position_size=Decimal("2500"),
        margin_required=Decimal("500"),
        setup_grade=SetupGrade.A,
        confidence_score=Decimal("85"),
        technical_explanation="Test",
        invalidation_conditions="SL break",
        should_trade=True,
    )


def test_open_from_signal() -> None:
    sim = PaperTradingSimulator()
    trade = sim.open_from_signal(1, _tradeable_signal())
    assert trade is not None
    assert trade.status == PaperTradeStatus.PENDING


def test_long_hits_stop_loss() -> None:
    sim = PaperTradingSimulator()
    trade = sim.open_from_signal(1, _tradeable_signal())
    assert trade is not None
    sim.update_with_price(trade.id, Decimal("50000"))
    result = sim.update_with_price(trade.id, Decimal("48900"))
    assert result is not None
    assert result.status == PaperTradeStatus.STOPPED
    assert result.pnl_usdt == Decimal("-50")


def test_long_hits_tp2() -> None:
    sim = PaperTradingSimulator()
    trade = sim.open_from_signal(1, _tradeable_signal())
    assert trade is not None
    sim.update_with_price(trade.id, Decimal("50000"))
    result = sim.update_with_price(trade.id, Decimal("52000"))
    assert result is not None
    assert result.status == PaperTradeStatus.CLOSED
    assert result.pnl_usdt == Decimal("100.00")


def test_stats() -> None:
    sim = PaperTradingSimulator()
    trade = sim.open_from_signal(1, _tradeable_signal())
    assert trade is not None
    sim.update_with_price(trade.id, Decimal("50000"))
    sim.update_with_price(trade.id, Decimal("52000"))
    stats = sim.get_stats()
    assert stats["total_closed"] == 1
    assert stats["wins"] == 1
