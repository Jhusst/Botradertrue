"""Indicadores vectorizados: valores de referencia y propiedades conocidas."""
import numpy as np
import pandas as pd
import pytest

from trading_bot.features.signals import indicators as ind


def _trending_df(periods: int = 300) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=periods, freq="1h", tz="UTC")
    close = pd.Series(np.linspace(100, 200, periods))
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": [100.0] * periods,
        }
    )


def _choppy_df(periods: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    dates = pd.date_range("2024-01-01", periods=periods, freq="1h", tz="UTC")
    close = pd.Series(100 + np.sin(np.linspace(0, 60, periods)) * 2 + rng.normal(0, 0.3, periods))
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": [100.0] * periods,
        }
    )


def test_ema_converge_a_la_serie_constante() -> None:
    series = pd.Series([50.0] * 100)
    assert ind.ema(series, 20).iloc[-1] == pytest.approx(50.0)


def test_rsi_sube_en_tendencia_alcista() -> None:
    df = _trending_df()
    rsi = ind.rsi(df["close"], 14)
    assert rsi.iloc[-1] > 70  # subida monótona → RSI alto


def test_macd_hist_positivo_en_tendencia_alcista() -> None:
    df = _trending_df()
    macd_df = ind.macd(df["close"])
    assert macd_df["macd"].iloc[-1] > 0
    assert set(macd_df.columns) == {"macd", "signal", "hist"}


def test_bollinger_geometria() -> None:
    df = _choppy_df()
    bb = ind.bollinger(df["close"])
    last = bb.dropna().iloc[-1]
    assert last["bb_lower"] < last["bb_mid"] < last["bb_upper"]
    assert last["bb_width_pct"] > 0


def test_adx_alto_en_tendencia_y_bajo_en_rango() -> None:
    adx_trend = ind.adx(_trending_df())["adx"].iloc[-1]
    adx_chop = ind.adx(_choppy_df())["adx"].iloc[-1]
    assert adx_trend > 25
    assert adx_trend > adx_chop


def test_vwap_ancla_diaria() -> None:
    df = _trending_df(48)  # 2 días UTC
    vwap = ind.vwap_daily(df)
    # Al inicio del segundo día el VWAP se reancla: igual al precio típico de su 1.ª vela
    idx_day2 = 24
    typical = (df["high"] + df["low"] + df["close"]) / 3
    assert vwap.iloc[idx_day2] == pytest.approx(typical.iloc[idx_day2])


def test_obv_acumula_con_subidas() -> None:
    df = _trending_df()
    obv = ind.obv(df)
    assert obv.iloc[-1] > 0
    assert obv.is_monotonic_increasing  # subida monótona → OBV monótono


def _persistent_series(periods: int, *, phi: float = 0.8, drift: float = 0.0, seed: int = 42) -> pd.Series:
    """Serie con retornos AR(1) positivos: persistente de verdad (Hurst > 0.5).

    Ojo: linspace+ruido NO es persistente — las diferencias del ruido blanco
    se autocorrelacionan negativo y el Hurst sale bajo (correctamente).
    """
    rng = np.random.default_rng(seed)
    innovations = rng.normal(0, 1, periods)
    returns = np.zeros(periods)
    for i in range(1, periods):
        returns[i] = phi * returns[i - 1] + innovations[i]
    return pd.Series(np.cumsum(returns + drift) + 1000)


def test_hurst_trending_vs_ruido() -> None:
    rng = np.random.default_rng(42)
    random_walk = pd.Series(np.cumsum(rng.normal(0, 1, 500)) + 1000)
    persistent = _persistent_series(500)
    h_rw = ind.hurst_exponent(random_walk)
    h_pers = ind.hurst_exponent(persistent)
    assert 0.35 <= h_rw <= 0.65  # random walk ≈ 0.5
    assert h_pers > 0.6  # retornos autocorrelacionados → persistente


def test_realized_volatility_mayor_con_mas_ruido() -> None:
    rng = np.random.default_rng(1)
    calm = pd.Series(100 + np.cumsum(rng.normal(0, 0.01, 200)))
    wild = pd.Series(100 + np.cumsum(rng.normal(0, 1.0, 200)))
    assert ind.realized_volatility(wild).iloc[-1] > ind.realized_volatility(calm).iloc[-1]


def test_rolling_percentile_extremos() -> None:
    rising = pd.Series(range(100), dtype=float)
    pct = ind.rolling_percentile(rising, 50)
    assert pct.iloc[-1] == 100.0  # el último valor siempre es el máximo de su ventana


def test_estrategia_sigue_identica_tras_migracion() -> None:
    """La delegación a indicators.py no cambia el comportamiento de la estrategia."""
    from trading_bot.features.signals.strategies.trend_pullback_mvp import (
        TrendPullbackMVPStrategy,
    )

    df = _trending_df()
    out = TrendPullbackMVPStrategy._add_indicators(df)
    assert {"ema20", "ema50", "ema200", "rsi", "atr"}.issubset(out.columns)
    assert not out.isna().any().any()
