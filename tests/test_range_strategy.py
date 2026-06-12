"""RangeBollingerMVPStrategy: opera laterales, se bloquea en tendencias."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from trading_bot.core.enums import TradeDirection
from trading_bot.features.regime.detector import MarketRegime, RegimeState
from trading_bot.features.signals.strategies.range_bollinger_mvp import RangeBollingerMVPStrategy
from trading_bot.features.signals.strategies.trend_pullback_mvp import MarketContext


def _df(close: np.ndarray, *, wick: float = 0.004) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(close), freq="1h", tz="UTC")
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": open_,
            "high": np.maximum(open_, close) * (1 + wick),
            "low": np.minimum(open_, close) * (1 - wick),
            "close": close,
            "volume": [100.0] * len(close),
        }
    )


def _range_market(periods: int = 400) -> pd.DataFrame:
    """Mercado lateral REAL: proceso Ornstein-Uhlenbeck (reversión a la media).

    Una senoidal pura no sirve: sus medio-ciclos largos disparan el ADX como
    si fueran tendencias. Los rangos de verdad son ruido que revierte.
    """
    rng = np.random.default_rng(8)
    close = np.zeros(periods)
    close[0] = 100.0
    for i in range(1, periods):
        close[i] = close[i - 1] + 0.12 * (100.0 - close[i - 1]) + rng.normal(0, 1.1)
    return _df(close)


def _ctx(df_1h: pd.DataFrame, regime: RegimeState | None = None) -> MarketContext:
    return MarketContext(
        symbol="BTC/USDT", df_4h=df_1h.iloc[::4].reset_index(drop=True),
        df_1h=df_1h, df_15m=df_1h, regime=regime,
    )


def _regime(kind: MarketRegime) -> RegimeState:
    return RegimeState(
        regime=kind, adx_4h=15.0, realized_vol_percentile=50.0,
        hurst=0.5, ema200_slope_pct=0.0, explanation="test",
    )


def test_genera_longs_y_shorts_en_rango_con_rr_2() -> None:
    strategy = RangeBollingerMVPStrategy()
    df = _range_market()
    longs = shorts = 0
    for i in range(80, len(df)):
        out = strategy.analyze(_ctx(df.iloc[: i + 1].reset_index(drop=True)))
        if out.direction == TradeDirection.NO_TRADE:
            continue
        risk = abs(out.entry_price - out.stop_loss)
        reward = abs(out.take_profit_2 - out.entry_price)
        assert risk > 0
        assert reward / risk >= Decimal("1.99")  # R:R 2.0 (con redondeo de quantize)
        if out.direction == TradeDirection.LONG:
            longs += 1
            assert out.stop_loss < out.entry_price < out.take_profit_2
        else:
            shorts += 1
            assert out.take_profit_2 < out.entry_price < out.stop_loss
    assert longs > 0, "debió comprar soporte alguna vez en 400 velas de rango"
    assert shorts > 0, "debió vender resistencia alguna vez en 400 velas de rango"


def test_bloqueada_en_tendencia_fuerte() -> None:
    strategy = RangeBollingerMVPStrategy()
    close = np.linspace(100, 200, 300)  # tendencia pura → ADX altísimo
    out = strategy.analyze(_ctx(_df(close)))
    assert out.direction == TradeDirection.NO_TRADE
    assert "ADX" in out.technical_explanation or "rango" in out.technical_explanation.lower()


def test_respeta_el_regimen_si_lo_conoce() -> None:
    strategy = RangeBollingerMVPStrategy()
    df = _range_market()
    out = strategy.analyze(_ctx(df, regime=_regime(MarketRegime.TREND_UP)))
    assert out.direction == TradeDirection.NO_TRADE
    assert "no opera" in out.technical_explanation


def test_datos_insuficientes() -> None:
    strategy = RangeBollingerMVPStrategy()
    out = strategy.analyze(_ctx(_range_market(40)))
    assert out.direction == TradeDirection.NO_TRADE


def test_generator_enruta_a_rango_solo_con_flag_y_regimen() -> None:
    from trading_bot.config.settings import Settings, get_settings
    from trading_bot.features.signals.generator import SignalGenerator
    from trading_bot.schemas.risk import AccountRiskState

    df = _range_market()
    account = AccountRiskState(balance_usdt=Decimal("500"), min_setup_grade="B")
    generator = SignalGenerator()

    spy = MagicMock(wraps=RangeBollingerMVPStrategy())
    spy.STRATEGY_NAME = "RangeBollingerMVP"
    generator.range_strategy = spy

    data = get_settings().model_dump()
    data.update(range_strategy_enabled=True, regime_detection_enabled=True, ml_filter_enabled=False)
    settings_on = Settings(**data)
    data_off = {**data, "range_strategy_enabled": False}
    settings_off = Settings(**data_off)

    ctx_range = _ctx(df, regime=_regime(MarketRegime.RANGE))

    with patch("trading_bot.features.signals.generator.get_settings", return_value=settings_on):
        generator.generate(ctx_range, account)
    assert spy.analyze.called, "con flag + RANGE debe usar la estrategia de rango"

    spy.analyze.reset_mock()
    with patch("trading_bot.features.signals.generator.get_settings", return_value=settings_off):
        generator.generate(ctx_range, account)
    assert not spy.analyze.called, "con flag apagado jamás se usa"

    spy.analyze.reset_mock()
    ctx_trend = _ctx(df, regime=_regime(MarketRegime.TREND_UP))
    with patch("trading_bot.features.signals.generator.get_settings", return_value=settings_on):
        generator.generate(ctx_trend, account)
    assert not spy.analyze.called, "fuera de RANGE jamás se usa"
