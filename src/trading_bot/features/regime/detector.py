"""Detección de régimen de mercado: tendencia / rango / alta volatilidad.

Reglas deterministas y testeables (v1):
- HIGH_VOL si la volatilidad realizada 24h está sobre el percentil 90
  de los últimos 90 días — manda sobre todo lo demás.
- TREND_UP/DOWN si ADX 4H > 22, pendiente EMA200 alineada y Hurst > 0.55.
- RANGE en cualquier otro caso.

La estrategia es de tendencia: en RANGE exige más confirmaciones, en
HIGH_VOL no opera, y contra-tendencia se bloquea.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from trading_bot.features.signals import indicators as ind


class MarketRegime(StrEnum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOL = "HIGH_VOL"


@dataclass(frozen=True)
class RegimeState:
    regime: MarketRegime
    adx_4h: float
    realized_vol_percentile: float
    hurst: float
    ema200_slope_pct: float
    explanation: str


class RegimeDetector:
    ADX_TREND_THRESHOLD = 22.0
    HURST_TREND_THRESHOLD = 0.55
    HIGH_VOL_PERCENTILE = 90.0
    RV_WINDOW_HOURS = 24
    RV_LOOKBACK_HOURS = 90 * 24
    SLOPE_LOOKBACK_4H = 10  # ~40 horas

    def detect(self, df_4h: pd.DataFrame, df_1h: pd.DataFrame) -> RegimeState | None:
        if len(df_4h) < 220 or len(df_1h) < self.RV_WINDOW_HOURS + 30:
            return None

        adx_df = ind.adx(df_4h, 14)
        adx_value = float(adx_df["adx"].iloc[-1])

        rv = ind.realized_volatility(df_1h["close"], window=self.RV_WINDOW_HOURS)
        lookback = min(self.RV_LOOKBACK_HOURS, len(rv.dropna()))
        rv_window = rv.dropna().tail(lookback)
        if rv_window.empty:
            return None
        rv_pct = float((rv_window <= rv_window.iloc[-1]).mean() * 100)

        hurst = ind.hurst_exponent(df_1h["close"].tail(200))

        ema200 = ind.ema(df_4h["close"], 200)
        past = float(ema200.iloc[-self.SLOPE_LOOKBACK_4H])
        slope_pct = (float(ema200.iloc[-1]) - past) / past * 100 if past > 0 else 0.0

        if rv_pct >= self.HIGH_VOL_PERCENTILE:
            regime = MarketRegime.HIGH_VOL
            explanation = f"Volatilidad realizada en percentil {rv_pct:.0f} (>={self.HIGH_VOL_PERCENTILE:.0f})"
        elif adx_value > self.ADX_TREND_THRESHOLD and hurst > self.HURST_TREND_THRESHOLD and slope_pct > 0:
            regime = MarketRegime.TREND_UP
            explanation = f"ADX {adx_value:.1f}, Hurst {hurst:.2f}, EMA200 al alza ({slope_pct:+.2f}%)"
        elif adx_value > self.ADX_TREND_THRESHOLD and hurst > self.HURST_TREND_THRESHOLD and slope_pct < 0:
            regime = MarketRegime.TREND_DOWN
            explanation = f"ADX {adx_value:.1f}, Hurst {hurst:.2f}, EMA200 a la baja ({slope_pct:+.2f}%)"
        else:
            regime = MarketRegime.RANGE
            explanation = f"Sin tendencia clara (ADX {adx_value:.1f}, Hurst {hurst:.2f})"

        return RegimeState(
            regime=regime,
            adx_4h=adx_value,
            realized_vol_percentile=rv_pct,
            hurst=hurst,
            ema200_slope_pct=slope_pct,
            explanation=explanation,
        )
