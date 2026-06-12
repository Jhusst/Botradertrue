"""Estrategia de RANGO: compra soporte / vende resistencia con Bollinger.

⚠️ VEREDICTO DEL BACKTEST (2024-2026, 10 símbolos, 2,067 trades): NEGATIVA.
Expectancia -0.04R a -0.26R según símbolo, profit factor 0.57-0.92, TODOS
perdedores. Las señales grado A rinden PEOR que las B (-0.15R vs -0.06R):
en cripto el RSI extremo anticipa continuación, no rebote. NO ACTIVAR
(range_strategy_enabled=false) sin rediseñar y revalidar. Se conserva como
referencia del experimento y por su arnés de integración/tests.

Complementa a TrendPullbackMVP: opera exactamente los períodos laterales
donde la de tendencia descansa. El generador la selecciona SOLO cuando el
RegimeDetector dice RANGE (y range_strategy_enabled=true); además se
auto-protege con sus propios bloqueos por si se usa standalone (backtest).

Setup LONG (espejo para SHORT):
- Precio toca/perfora la banda inferior de Bollinger (20, 2σ) en 1H
- RSI en sobreventa (<=32; extremo <=25 sube el grado)
- Vela de rechazo (cierre verde tras el toque)
- El rango tiene espacio: TP2 (2R) debe caber dentro de la banda opuesta
- SL = 1×ATR bajo la entrada · TP1 = +1R · TP2 = +2R (cumple R:R mínimo 2.0)

Bloqueos: ADX 1H > 25 (las bandas "caminan" en tendencia), volatilidad
explosiva (>2x media 30), datos insuficientes, régimen no-RANGE si se conoce.
"""
from __future__ import annotations

from decimal import Decimal

import pandas as pd

from trading_bot.core.asset_catalog import quantize_price
from trading_bot.core.enums import SetupGrade, TradeDirection
from trading_bot.features.signals import indicators as ind
from trading_bot.features.signals.strategies.trend_pullback_mvp import (
    MarketContext,
    StrategyOutput,
)


class RangeBollingerMVPStrategy:
    """Reversión a la media dentro de rangos laterales."""

    STRATEGY_NAME = "RangeBollingerMVP"

    MIN_BARS_1H = 60
    ADX_MAX = 25.0          # por encima de esto las bandas caminan (tendencia)
    RSI_LONG_MAX = 32.0
    RSI_LONG_GRADE_A = 25.0
    RSI_SHORT_MIN = 68.0
    RSI_SHORT_GRADE_A = 75.0
    SL_ATR_MULT = Decimal("1.0")
    BAND_TOUCH_TOLERANCE = 0.002  # 0.2% de margen para "tocar" la banda

    def analyze(self, ctx: MarketContext) -> StrategyOutput:
        df = self._add_indicators(ctx.df_1h)
        if len(df) < self.MIN_BARS_1H:
            return self._no_trade("Datos insuficientes para análisis de rango.")

        last = df.iloc[-1]
        atr = Decimal(str(last["atr"]))
        close = float(last["close"])
        atr_pct = Decimal(str(round(float(last["atr"]) / close * 100, 4))) if close > 0 else None

        # Régimen conocido (live): esta estrategia SOLO opera rangos
        if ctx.regime is not None and ctx.regime.regime.value != "RANGE":
            return self._no_trade(
                f"Régimen {ctx.regime.regime.value}: la estrategia de rango no opera.", atr_pct
            )

        # Auto-protección standalone (backtest): nada de tendencias fuertes
        if float(last["adx"]) > self.ADX_MAX:
            return self._no_trade(
                f"ADX {last['adx']:.1f} > {self.ADX_MAX}: tendencia activa, no es rango.", atr_pct
            )

        # Volatilidad explosiva: el rango se está rompiendo
        atr_avg = df["atr"].rolling(30).mean().iloc[-1]
        if pd.notna(atr_avg) and float(last["atr"]) > float(atr_avg) * 2:
            return self._no_trade("Volatilidad excesiva (>2x media 30): posible ruptura.", atr_pct)

        rsi = float(last["rsi"])
        bb_lower = float(last["bb_lower"])
        bb_upper = float(last["bb_upper"])
        is_green = last["close"] > last["open"]
        is_red = last["close"] < last["open"]

        touched_lower = float(last["low"]) <= bb_lower * (1 + self.BAND_TOUCH_TOLERANCE)
        touched_upper = float(last["high"]) >= bb_upper * (1 - self.BAND_TOUCH_TOLERANCE)

        if touched_lower and rsi <= self.RSI_LONG_MAX and is_green:
            return self._build_signal(TradeDirection.LONG, df, atr, atr_pct, rsi, ctx)
        if touched_upper and rsi >= self.RSI_SHORT_MIN and is_red:
            return self._build_signal(TradeDirection.SHORT, df, atr, atr_pct, rsi, ctx)

        return self._no_trade("Sin toque de banda con sobrecompra/sobreventa y rechazo.", atr_pct)

    def _build_signal(
        self,
        direction: TradeDirection,
        df: pd.DataFrame,
        atr: Decimal,
        atr_pct: Decimal | None,
        rsi: float,
        ctx: MarketContext,
    ) -> StrategyOutput:
        last = df.iloc[-1]
        entry = quantize_price(Decimal(str(last["close"])), ctx.symbol)
        reasons: list[str] = []

        if direction == TradeDirection.LONG:
            stop = quantize_price(entry - self.SL_ATR_MULT * atr, ctx.symbol)
            risk = entry - stop
            tp1 = quantize_price(entry + risk, ctx.symbol)
            tp2 = quantize_price(entry + risk * Decimal("2"), ctx.symbol)
            # El objetivo debe caber dentro del rango (banda opuesta)
            if float(tp2) > float(last["bb_upper"]):
                return self._no_trade(
                    "Rango demasiado estrecho: TP2 (2R) no cabe bajo la banda superior.", atr_pct
                )
            grade_a = rsi <= self.RSI_LONG_GRADE_A
            reasons.append(f"Toque de banda inferior de Bollinger con RSI {rsi:.1f} (sobreventa).")
            reasons.append("Vela verde de rechazo en soporte del rango.")
            invalidation = f"Cierre de vela 1H bajo {stop} o ADX 1H sobre {self.ADX_MAX} (ruptura)."
        else:
            stop = quantize_price(entry + self.SL_ATR_MULT * atr, ctx.symbol)
            risk = stop - entry
            tp1 = quantize_price(entry - risk, ctx.symbol)
            tp2 = quantize_price(entry - risk * Decimal("2"), ctx.symbol)
            if float(tp2) < float(last["bb_lower"]):
                return self._no_trade(
                    "Rango demasiado estrecho: TP2 (2R) no cabe sobre la banda inferior.", atr_pct
                )
            grade_a = rsi >= self.RSI_SHORT_GRADE_A
            reasons.append(f"Toque de banda superior de Bollinger con RSI {rsi:.1f} (sobrecompra).")
            reasons.append("Vela roja de rechazo en resistencia del rango.")
            invalidation = f"Cierre de vela 1H sobre {stop} o ADX 1H sobre {self.ADX_MAX} (ruptura)."

        if risk <= 0:
            return self._no_trade("Riesgo no positivo (ATR degenerado).", atr_pct)

        reasons.append(f"ADX {last['adx']:.1f} confirma mercado lateral.")
        grade = SetupGrade.A if grade_a else SetupGrade.B
        confidence = Decimal("80") if grade is SetupGrade.A else Decimal("62")

        return StrategyOutput(
            direction=direction,
            setup_grade=grade,
            primary_timeframe="1h",
            entry_price=entry,
            stop_loss=stop,
            take_profit_1=tp1,
            take_profit_2=tp2,
            confidence_score=confidence,
            technical_explanation=" | ".join(reasons),
            invalidation_conditions=invalidation,
            atr_percent=atr_pct,
        )

    def _no_trade(self, reason: str, atr_pct: Decimal | None = None) -> StrategyOutput:
        return StrategyOutput(
            direction=TradeDirection.NO_TRADE,
            setup_grade=SetupGrade.C,
            primary_timeframe="1h",
            entry_price=None,
            stop_loss=None,
            take_profit_1=None,
            take_profit_2=None,
            confidence_score=Decimal("0"),
            technical_explanation=reason,
            invalidation_conditions="N/A",
            atr_percent=atr_pct,
        )

    @staticmethod
    def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        result["rsi"] = ind.rsi(result["close"], 14)
        result["atr"] = ind.atr(result, 14)
        bb = ind.bollinger(result["close"], 20, 2.0)
        result["bb_upper"] = bb["bb_upper"]
        result["bb_mid"] = bb["bb_mid"]
        result["bb_lower"] = bb["bb_lower"]
        adx_df = ind.adx(result, 14)
        result["adx"] = adx_df["adx"]
        return result.dropna()
