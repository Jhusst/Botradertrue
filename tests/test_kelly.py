"""KellyCalculator: fórmula, caps y la regla de oro (solo reduce)."""
from decimal import Decimal

import pytest

from trading_bot.config.settings import Settings, get_settings
from trading_bot.features.signals.risk.kelly import KellyCalculator, TradeStats


def _settings(**overrides) -> Settings:
    data = get_settings().model_dump()
    defaults = {
        "kelly_enabled": True,
        "kelly_fraction": 0.25,
        "kelly_min_trades": 20,
        "kelly_cap_risk_percent": 0.5,
        "kelly_floor_risk_percent": 0.1,
    }
    data.update({**defaults, **overrides})
    return Settings(**data)


def test_formula_kelly_valores_conocidos() -> None:
    # W=0.5, payoff=2 → f* = 0.5 - 0.5/2 = 0.25
    calc = KellyCalculator(_settings())
    stats = TradeStats(n_trades=100, win_rate=0.5, avg_win_r=2.0, avg_loss_r=1.0)
    assert calc.kelly_fraction(stats) == pytest.approx(0.25)


def test_kelly_negativo_devuelve_floor() -> None:
    calc = KellyCalculator(_settings())
    # Sin edge: W=0.3, payoff=1 → f* = 0.3 - 0.7 = -0.4 → floor
    stats = TradeStats(n_trades=100, win_rate=0.3, avg_win_r=1.0, avg_loss_r=1.0)
    assert calc.kelly_fraction(stats) == 0.0
    assert calc.risk_percent(stats) == Decimal("0.1")


def test_cap_y_floor_se_respetan() -> None:
    calc = KellyCalculator(_settings())
    # Edge enorme: f*=0.25 → 0.25*0.25*100 = 6.25% → cap 0.5%
    stats = TradeStats(n_trades=100, win_rate=0.5, avg_win_r=2.0, avg_loss_r=1.0)
    assert calc.risk_percent(stats) == Decimal("0.5")


def test_sin_historial_suficiente_no_opina() -> None:
    calc = KellyCalculator(_settings())
    stats = TradeStats(n_trades=10, win_rate=0.5, avg_win_r=2.0, avg_loss_r=1.0)
    assert calc.risk_percent(stats) is None
    assert calc.risk_percent(None) is None


def test_probabilidad_ml_modula_kelly() -> None:
    calc = KellyCalculator(_settings(kelly_cap_risk_percent=10.0))
    stats = TradeStats(n_trades=100, win_rate=0.5, avg_win_r=2.0, avg_loss_r=1.0)
    base = calc.risk_percent(stats)
    confident = calc.risk_percent(stats, ml_probability=0.7)
    doubtful = calc.risk_percent(stats, ml_probability=0.35)
    assert confident > base       # más convicción → más riesgo (dentro del cap)
    assert doubtful < base        # menos convicción → menos riesgo


def test_stats_from_r_multiples() -> None:
    r = [2.0] * 10 + [-1.0] * 10
    stats = KellyCalculator.stats_from_r_multiples(r, min_trades=20)
    assert stats is not None
    assert stats.win_rate == 0.5
    assert stats.avg_win_r == 2.0
    assert stats.avg_loss_r == 1.0
    assert KellyCalculator.stats_from_r_multiples(r[:5], min_trades=20) is None


def test_kelly_solo_reduce_en_generator() -> None:
    """Integración: con Kelly activo, el riesgo final nunca supera el del RiskManager."""
    from decimal import Decimal
    from unittest.mock import patch

    from trading_bot.features.signals.generator import SignalGenerator
    from trading_bot.infrastructure.market_data.ccxt_client import DataCollector
    from trading_bot.features.signals.strategies.trend_pullback_mvp import MarketContext
    from trading_bot.schemas.risk import AccountRiskState

    data = DataCollector.generate_trending_bullish_data(500)
    ctx = MarketContext(symbol="BTC/USDT", df_4h=data["4h"], df_1h=data["1h"], df_15m=data["15m"])
    account = AccountRiskState(balance_usdt=Decimal("500"), min_setup_grade="B")

    generator = SignalGenerator()
    settings = _settings()
    with patch("trading_bot.features.signals.generator.get_settings", return_value=settings):
        baseline = generator.generate(ctx, account)
        # Stats con edge brutal: Kelly querría >cap, pero solo puede REDUCIR
        stats = TradeStats(n_trades=100, win_rate=0.9, avg_win_r=3.0, avg_loss_r=0.5)
        with_kelly = generator.generate(ctx, account, trade_stats=stats)

    if baseline.should_trade and with_kelly.should_trade:
        assert with_kelly.risk_percent <= baseline.risk_percent
