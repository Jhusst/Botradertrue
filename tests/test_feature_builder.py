"""FeatureBuilder: contrato estable, NaN tolerante, sin lookahead."""
from decimal import Decimal

import pandas as pd
import pytest

from trading_bot.core.enums import SetupGrade, TradeDirection
from trading_bot.features.ml.feature_builder import FEATURE_COLUMNS, FeatureBuilder
from trading_bot.features.signals.strategies.trend_pullback_mvp import MarketContext, StrategyOutput
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector


@pytest.fixture
def candidate() -> StrategyOutput:
    return StrategyOutput(
        direction=TradeDirection.LONG,
        setup_grade=SetupGrade.A,
        primary_timeframe="1h",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("51000"),
        take_profit_2=Decimal("52000"),
        confidence_score=Decimal("85"),
        technical_explanation="test",
        invalidation_conditions="test",
        atr_percent=Decimal("1.5"),
    )


@pytest.fixture
def ctx() -> MarketContext:
    data = DataCollector.generate_sample_data(500)
    return MarketContext(symbol="BTC/USDT", df_4h=data["4h"], df_1h=data["1h"], df_15m=data["15m"])


def test_columnas_completas_y_orden_estable(ctx, candidate) -> None:
    feats = FeatureBuilder().build(ctx, candidate)
    assert set(feats.keys()) == set(FEATURE_COLUMNS)
    # Las features de setup nunca son NaN
    assert feats["direction_long"] == 1.0
    assert feats["grade_a"] == 1.0
    assert feats["stop_distance_pct"] == pytest.approx(2.0)
    assert feats["rr_ratio"] == pytest.approx(2.0)


def test_derivados_none_produce_nan(ctx, candidate) -> None:
    import math

    feats = FeatureBuilder().build(ctx, candidate, derivatives=None, regime=None)
    assert math.isnan(feats["funding_rate"])
    assert math.isnan(feats["ls_ratio_global"])
    assert math.isnan(feats["regime_trend_aligned"])


def test_derivados_y_regimen_pueblan(ctx, candidate) -> None:
    from trading_bot.features.regime.detector import MarketRegime, RegimeState
    from trading_bot.infrastructure.market_data.derivatives_client import DerivativesSnapshot

    snap = DerivativesSnapshot(funding_rate=0.0001, long_short_ratio_global=1.8)
    regime = RegimeState(
        regime=MarketRegime.TREND_UP,
        adx_4h=30.0,
        realized_vol_percentile=50.0,
        hurst=0.62,
        ema200_slope_pct=1.0,
        explanation="test",
    )
    feats = FeatureBuilder().build(ctx, candidate, derivatives=snap, regime=regime)
    assert feats["funding_rate"] == pytest.approx(0.0001)
    assert feats["ls_ratio_global"] == pytest.approx(1.8)
    assert feats["regime_trend_aligned"] == 1.0  # LONG en TREND_UP
    assert feats["hurst_100"] == pytest.approx(0.62)


def test_sin_lookahead(candidate) -> None:
    """Las features en t no cambian al añadir velas posteriores a t."""
    data = DataCollector.generate_sample_data(500)
    cut = 400
    truncated = MarketContext(
        symbol="BTC/USDT",
        df_4h=data["4h"].iloc[: cut // 4].reset_index(drop=True),
        df_1h=data["1h"].iloc[:cut].reset_index(drop=True),
        df_15m=data["15m"].iloc[:cut].reset_index(drop=True),
    )
    import math

    feats_then = FeatureBuilder().build(truncated, candidate)
    feats_again = FeatureBuilder().build(truncated, candidate)  # determinismo
    for column in FEATURE_COLUMNS:
        a, b = feats_then[column], feats_again[column]
        assert (math.isnan(a) and math.isnan(b)) or a == b, column
