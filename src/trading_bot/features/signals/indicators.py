"""Indicadores técnicos vectorizados (pandas/numpy puros).

Sin pandas-ta ni TA-Lib (problemáticos en Windows). Funciones puras:
mismas entradas → mismas salidas, usables en estrategia, régimen,
feature builder del ML y backtest sin divergencias.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    # Sin pérdidas en la ventana → RSI 100 (no NaN); sin movimiento → 50
    result = result.mask((loss == 0) & (gain > 0), 100.0)
    result = result.mask((loss == 0) & (gain == 0), 50.0)
    return result


def true_range(df: pd.DataFrame) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    return pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).rolling(period).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line}
    )


def bollinger(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    width_pct = (upper - lower) / mid * 100
    pct_b = (series - lower) / (upper - lower)
    return pd.DataFrame(
        {"bb_upper": upper, "bb_mid": mid, "bb_lower": lower, "bb_width_pct": width_pct, "bb_pct_b": pct_b}
    )


def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX de Wilder con +DI/-DI."""
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=df.index
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=df.index
    )
    tr = true_range(df)

    alpha = 1.0 / period
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_w.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_w.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx_series = dx.ewm(alpha=alpha, adjust=False).mean()
    return pd.DataFrame({"adx": adx_series, "plus_di": plus_di, "minus_di": minus_di})


def vwap_daily(df: pd.DataFrame) -> pd.Series:
    """VWAP con ancla diaria UTC (requiere columna timestamp)."""
    typical = (df["high"] + df["low"] + df["close"]) / 3
    day = pd.to_datetime(df["timestamp"], utc=True).dt.floor("D")
    pv = typical * df["volume"]
    cum_pv = pv.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def realized_volatility(series: pd.Series, window: int = 24, *, annualize_periods: int = 8760) -> pd.Series:
    """Volatilidad realizada de log-returns, anualizada (1h → 8760 períodos/año)."""
    log_ret = np.log(series / series.shift())
    return log_ret.rolling(window).std() * np.sqrt(annualize_periods)


def hurst_exponent(series: pd.Series, max_lag: int = 20) -> float:
    """Exponente de Hurst (rescaled-range simplificado vía varianza de diferencias).

    ~0.5 random walk; >0.55 tendencial (persistente); <0.45 reversión a la media.
    """
    values = np.asarray(series.dropna(), dtype=float)
    if len(values) < max_lag * 2:
        return 0.5
    lags = range(2, max_lag)
    tau = [np.std(values[lag:] - values[:-lag]) for lag in lags]
    tau = np.asarray(tau)
    if (tau <= 0).any():
        return 0.5
    slope = np.polyfit(np.log(list(lags)), np.log(tau), 1)[0]
    return float(slope)


def rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    """Percentil [0,100] del último valor dentro de su ventana."""
    return series.rolling(window).apply(
        lambda w: (w <= w[-1]).mean() * 100 if len(w) else np.nan, raw=True
    )
