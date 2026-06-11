"""RegimeDetector: tendencia, rango y alta volatilidad."""
import numpy as np
import pandas as pd

from trading_bot.features.regime import MarketRegime, RegimeDetector


def _df(close: np.ndarray, freq: str) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(close), freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": close,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": [100.0] * len(close),
        }
    )


def _persistent_close(periods: int, *, start: float, drift: float, seed: int, phi: float = 0.85) -> np.ndarray:
    """Cierres con retornos AR(1) + drift: tendencia PERSISTENTE (Hurst > 0.55)."""
    rng = np.random.default_rng(seed)
    innovations = rng.normal(0, 0.3, periods)
    returns = np.zeros(periods)
    for i in range(1, periods):
        returns[i] = phi * returns[i - 1] + innovations[i]
    return start + np.cumsum(returns + drift)


def test_detecta_trend_up_en_alcista_sostenido() -> None:
    close_4h = _persistent_close(300, start=100, drift=0.8, seed=5)
    close_1h = _persistent_close(400, start=250, drift=0.3, seed=6)
    state = RegimeDetector().detect(_df(close_4h, "4h"), _df(close_1h, "1h"))
    assert state is not None
    assert state.regime == MarketRegime.TREND_UP
    assert state.adx_4h > 22


def test_detecta_range_en_lateral() -> None:
    rng = np.random.default_rng(9)
    close_4h = 100 + np.sin(np.linspace(0, 50, 300)) * 1.5 + rng.normal(0, 0.3, 300)
    close_1h = 100 + np.sin(np.linspace(0, 80, 400)) * 1.0 + rng.normal(0, 0.2, 400)
    state = RegimeDetector().detect(_df(close_4h, "4h"), _df(close_1h, "1h"))
    assert state is not None
    assert state.regime == MarketRegime.RANGE


def test_high_vol_prevalece_sobre_tendencia() -> None:
    rng = np.random.default_rng(2)
    close_4h = np.linspace(100, 300, 300) + rng.normal(0, 0.5, 300)
    # 1h tranquila salvo el último día: explosión de volatilidad
    close_1h = np.linspace(250, 300, 400) + rng.normal(0, 0.05, 400)
    close_1h[-24:] += np.cumsum(rng.normal(0, 8, 24))
    state = RegimeDetector().detect(_df(close_4h, "4h"), _df(close_1h, "1h"))
    assert state is not None
    assert state.regime == MarketRegime.HIGH_VOL
    assert state.realized_vol_percentile >= 90


def test_datos_insuficientes_devuelve_none() -> None:
    close = np.linspace(100, 110, 50)
    state = RegimeDetector().detect(_df(close, "4h"), _df(close, "1h"))
    assert state is None
