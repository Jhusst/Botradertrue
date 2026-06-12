"""Features para el meta-modelo: computables igual en backtest y en live.

Contrato estable: FEATURE_COLUMNS define orden y nombres; el modelo se
persiste junto a esta lista y el predictor valida compatibilidad.
NaN está permitido (LightGBM lo maneja nativo) — derivados con huecos
o régimen ausente simplemente quedan NaN.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from trading_bot.features.signals import indicators as ind
from trading_bot.features.signals.strategies.trend_pullback_mvp import MarketContext, StrategyOutput

FEATURE_COLUMNS: list[str] = [
    # Tendencia
    "ema20_50_ratio_1h",
    "close_ema200_dist_pct_4h",
    "ema200_slope_pct_4h",
    "adx_4h",
    "adx_1h",
    "di_diff_1h",
    # Momentum
    "rsi_1h",
    "rsi_4h",
    "macd_hist_norm_1h",
    "roc_4_1h",
    "roc_24_1h",
    # Volatilidad
    "atr_pct_1h",
    "bb_width_pct_1h",
    "rv_24h_vs_7d_ratio",
    # Volumen
    "vol_zscore_20_15m",
    "rel_volume_1h",
    "obv_slope_20_1h",
    # Estructura
    "dist_vwap_daily_pct",
    "dist_swing_high_20_pct",
    "dist_swing_low_20_pct",
    "body_ratio_last_1h",
    # Price action / patrones de velas (el modelo decide cuáles predicen)
    "upper_wick_ratio_1h",
    "lower_wick_ratio_1h",
    "bullish_engulfing",
    "bearish_engulfing",
    "hammer",
    "shooting_star",
    "doji",
    "candle_streak",
    "range_vs_atr_1h",
    "close_pos_in_candle_1h",
    # Setup
    "direction_long",
    "grade_a",
    "stop_distance_pct",
    "rr_ratio",
    "confidence",
    # Temporal
    "hour_sin",
    "hour_cos",
    "day_of_week",
    # Derivados (alt-data, nullable)
    "funding_rate",
    "funding_zscore_7d",
    "oi_change_1h_pct",
    "oi_change_24h_pct",
    "ls_ratio_global",
    "ls_ratio_top",
    "taker_ratio",
    # Régimen
    "regime_trend_aligned",
    "hurst_100",
]


def _safe(value) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


class FeatureBuilder:
    def build(
        self,
        ctx: MarketContext,
        candidate: StrategyOutput,
        derivatives=None,
        regime=None,
    ) -> dict[str, float]:
        df_1h = ctx.df_1h
        df_4h = ctx.df_4h
        df_15m = ctx.df_15m
        close_1h = df_1h["close"]
        close_4h = df_4h["close"]
        last_close = float(close_1h.iloc[-1])

        nan = float("nan")
        f: dict[str, float] = dict.fromkeys(FEATURE_COLUMNS, nan)

        # --- Tendencia
        ema20 = ind.ema(close_1h, 20).iloc[-1]
        ema50 = ind.ema(close_1h, 50).iloc[-1]
        f["ema20_50_ratio_1h"] = _safe(ema20 / ema50 - 1) * 100 if ema50 else nan
        ema200_4h = ind.ema(close_4h, 200)
        if len(ema200_4h.dropna()) > 10:
            f["close_ema200_dist_pct_4h"] = _safe(
                (float(close_4h.iloc[-1]) - float(ema200_4h.iloc[-1])) / float(ema200_4h.iloc[-1]) * 100
            )
            past = float(ema200_4h.iloc[-10])
            if past > 0:
                f["ema200_slope_pct_4h"] = _safe((float(ema200_4h.iloc[-1]) - past) / past * 100)
        if len(df_4h) >= 30:
            adx_4h = ind.adx(df_4h)
            f["adx_4h"] = _safe(adx_4h["adx"].iloc[-1])
        if len(df_1h) >= 30:
            adx_1h = ind.adx(df_1h)
            f["adx_1h"] = _safe(adx_1h["adx"].iloc[-1])
            f["di_diff_1h"] = _safe(adx_1h["plus_di"].iloc[-1] - adx_1h["minus_di"].iloc[-1])

        # --- Momentum
        f["rsi_1h"] = _safe(ind.rsi(close_1h).iloc[-1])
        f["rsi_4h"] = _safe(ind.rsi(close_4h).iloc[-1])
        macd_df = ind.macd(close_1h)
        if last_close > 0:
            f["macd_hist_norm_1h"] = _safe(macd_df["hist"].iloc[-1] / last_close * 100)
        if len(close_1h) > 24:
            f["roc_4_1h"] = _safe((last_close / float(close_1h.iloc[-5]) - 1) * 100)
            f["roc_24_1h"] = _safe((last_close / float(close_1h.iloc[-25]) - 1) * 100)

        # --- Volatilidad
        atr_1h = ind.atr(df_1h).iloc[-1]
        if last_close > 0:
            f["atr_pct_1h"] = _safe(atr_1h / last_close * 100)
        bb = ind.bollinger(close_1h)
        f["bb_width_pct_1h"] = _safe(bb["bb_width_pct"].iloc[-1])
        rv = ind.realized_volatility(close_1h, window=24)
        rv_7d = ind.realized_volatility(close_1h, window=168)
        if len(rv.dropna()) and len(rv_7d.dropna()) and float(rv_7d.iloc[-1] or 0) > 0:
            f["rv_24h_vs_7d_ratio"] = _safe(rv.iloc[-1] / rv_7d.iloc[-1])

        # --- Volumen
        if len(df_15m) >= 21:
            vol = df_15m["volume"]
            mean = vol.rolling(20).mean().iloc[-1]
            std = vol.rolling(20).std().iloc[-1]
            if std and std > 0:
                f["vol_zscore_20_15m"] = _safe((float(vol.iloc[-1]) - mean) / std)
        vol_1h_mean = df_1h["volume"].rolling(20).mean().iloc[-1]
        if vol_1h_mean and vol_1h_mean > 0:
            f["rel_volume_1h"] = _safe(float(df_1h["volume"].iloc[-1]) / vol_1h_mean)
        obv = ind.obv(df_1h)
        if len(obv) >= 21 and last_close > 0:
            f["obv_slope_20_1h"] = _safe((float(obv.iloc[-1]) - float(obv.iloc[-21])) / 20)

        # --- Estructura
        if "timestamp" in df_1h.columns:
            vwap = ind.vwap_daily(df_1h)
            v = float(vwap.iloc[-1]) if not pd.isna(vwap.iloc[-1]) else None
            if v:
                f["dist_vwap_daily_pct"] = _safe((last_close - v) / v * 100)
        if len(df_1h) >= 21:
            swing_high = float(df_1h["high"].rolling(20).max().iloc[-2])
            swing_low = float(df_1h["low"].rolling(20).min().iloc[-2])
            if swing_high > 0:
                f["dist_swing_high_20_pct"] = _safe((swing_high - last_close) / last_close * 100)
            if swing_low > 0:
                f["dist_swing_low_20_pct"] = _safe((last_close - swing_low) / last_close * 100)
        last = df_1h.iloc[-1]
        candle_range = float(last["high"] - last["low"])
        if candle_range > 0:
            f["body_ratio_last_1h"] = _safe(abs(float(last["close"] - last["open"])) / candle_range)

        # --- Price action / patrones de velas (1h)
        if candle_range > 0 and len(df_1h) >= 6:
            prev = df_1h.iloc[-2]
            body_top = max(float(last["open"]), float(last["close"]))
            body_bottom = min(float(last["open"]), float(last["close"]))
            body = body_top - body_bottom
            upper_wick = float(last["high"]) - body_top
            lower_wick = body_bottom - float(last["low"])
            body_ratio = body / candle_range

            f["upper_wick_ratio_1h"] = _safe(upper_wick / candle_range)
            f["lower_wick_ratio_1h"] = _safe(lower_wick / candle_range)
            f["close_pos_in_candle_1h"] = _safe((float(last["close"]) - float(last["low"])) / candle_range)

            last_green = float(last["close"]) > float(last["open"])
            last_red = float(last["close"]) < float(last["open"])
            prev_green = float(prev["close"]) > float(prev["open"])
            prev_red = float(prev["close"]) < float(prev["open"])
            prev_body_top = max(float(prev["open"]), float(prev["close"]))
            prev_body_bottom = min(float(prev["open"]), float(prev["close"]))

            f["bullish_engulfing"] = float(
                last_green and prev_red and body_bottom <= prev_body_bottom and body_top >= prev_body_top
            )
            f["bearish_engulfing"] = float(
                last_red and prev_green and body_bottom <= prev_body_bottom and body_top >= prev_body_top
            )
            f["hammer"] = float(lower_wick >= 2 * body and upper_wick <= body and body_ratio < 0.35)
            f["shooting_star"] = float(upper_wick >= 2 * body and lower_wick <= body and body_ratio < 0.35)
            f["doji"] = float(body_ratio < 0.1)

            # Racha con signo: +n velas verdes seguidas / -n rojas
            streak = 0
            for i in range(1, min(6, len(df_1h)) + 1):
                candle = df_1h.iloc[-i]
                if float(candle["close"]) > float(candle["open"]):
                    if streak < 0:
                        break
                    streak += 1
                elif float(candle["close"]) < float(candle["open"]):
                    if streak > 0:
                        break
                    streak -= 1
                else:
                    break
            f["candle_streak"] = float(streak)

            if atr_1h and float(atr_1h) > 0:
                f["range_vs_atr_1h"] = _safe(candle_range / float(atr_1h))

        # --- Setup
        f["direction_long"] = 1.0 if candidate.direction.value == "LONG" else 0.0
        f["grade_a"] = 1.0 if candidate.setup_grade.value == "A" else 0.0
        if candidate.entry_price and candidate.stop_loss and candidate.entry_price > 0:
            f["stop_distance_pct"] = _safe(
                abs(float(candidate.entry_price) - float(candidate.stop_loss))
                / float(candidate.entry_price)
                * 100
            )
            if candidate.take_profit_2:
                risk = abs(float(candidate.entry_price) - float(candidate.stop_loss))
                reward = abs(float(candidate.take_profit_2) - float(candidate.entry_price))
                if risk > 0:
                    f["rr_ratio"] = _safe(reward / risk)
        f["confidence"] = _safe(candidate.confidence_score)

        # --- Temporal
        if "timestamp" in df_1h.columns:
            ts = pd.to_datetime(df_1h["timestamp"].iloc[-1], utc=True)
            f["hour_sin"] = math.sin(2 * math.pi * ts.hour / 24)
            f["hour_cos"] = math.cos(2 * math.pi * ts.hour / 24)
            f["day_of_week"] = float(ts.dayofweek)

        # --- Derivados (nullable)
        if derivatives is not None:
            f["funding_rate"] = _safe(derivatives.funding_rate)
            f["funding_zscore_7d"] = _safe(derivatives.funding_zscore_7d)
            f["oi_change_1h_pct"] = _safe(derivatives.oi_change_1h_pct)
            f["oi_change_24h_pct"] = _safe(derivatives.oi_change_24h_pct)
            f["ls_ratio_global"] = _safe(derivatives.long_short_ratio_global)
            f["ls_ratio_top"] = _safe(derivatives.long_short_ratio_top)
            f["taker_ratio"] = _safe(derivatives.taker_buy_sell_ratio)

        # --- Régimen
        if regime is not None:
            aligned = (
                (regime.regime.value == "TREND_UP" and candidate.direction.value == "LONG")
                or (regime.regime.value == "TREND_DOWN" and candidate.direction.value == "SHORT")
            )
            f["regime_trend_aligned"] = 1.0 if aligned else 0.0
            f["hurst_100"] = _safe(regime.hurst)

        return f

    @staticmethod
    def to_row(features: dict[str, float]) -> np.ndarray:
        return np.array([[features[c] for c in FEATURE_COLUMNS]], dtype=float)
