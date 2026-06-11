from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pandas as pd

from trading_bot.core.asset_catalog import quantize_price
from trading_bot.core.enums import SetupGrade, TradeDirection

if TYPE_CHECKING:
    from trading_bot.features.regime.detector import RegimeState
    from trading_bot.infrastructure.market_data.derivatives_client import DerivativesSnapshot


@dataclass
class MarketContext:
    symbol: str
    df_4h: pd.DataFrame
    df_1h: pd.DataFrame
    df_15m: pd.DataFrame
    has_high_impact_event: bool = False
    regime: "RegimeState | None" = None
    derivatives: "DerivativesSnapshot | Any | None" = None


@dataclass
class StrategyOutput:
    direction: TradeDirection
    setup_grade: SetupGrade
    primary_timeframe: str
    entry_price: Decimal | None
    stop_loss: Decimal | None
    take_profit_1: Decimal | None
    take_profit_2: Decimal | None
    confidence_score: Decimal
    technical_explanation: str
    invalidation_conditions: str
    atr_percent: Decimal | None


class TrendPullbackMVPStrategy:
    """Estrategia MVP: tendencia en 4H + pullback en 1H + confirmación en 15M."""

    STRATEGY_NAME = "TrendPullbackMVP"

    def analyze(self, ctx: MarketContext) -> StrategyOutput:
        df_4h = self._add_indicators(ctx.df_4h)
        df_1h = self._add_indicators(ctx.df_1h)
        df_15m = self._add_indicators(ctx.df_15m)

        if len(df_4h) < 200 or len(df_1h) < 50 or len(df_15m) < 30:
            return self._no_trade("Datos insuficientes para análisis.")

        last_4h = df_4h.iloc[-1]
        last_1h = df_1h.iloc[-1]
        last_15m = df_15m.iloc[-1]
        prev_1h = df_1h.iloc[-2]

        atr_pct = Decimal(str((last_1h["atr"] / last_1h["close"] * 100).round(4)))

        long_score = 0
        short_score = 0
        reasons: list[str] = []

        # Tendencia 4H
        if last_4h["close"] > last_4h["ema200"]:
            long_score += 2
            reasons.append("Precio sobre EMA200 en 4H (tendencia alcista).")
        elif last_4h["close"] < last_4h["ema200"]:
            short_score += 2
            reasons.append("Precio bajo EMA200 en 4H (tendencia bajista).")

        # Momentum 1H
        if last_1h["ema20"] > last_1h["ema50"]:
            long_score += 1
        elif last_1h["ema20"] < last_1h["ema50"]:
            short_score += 1

        # RSI 1H
        rsi = last_1h["rsi"]
        if 40 <= rsi <= 60:
            if long_score > short_score:
                long_score += 1
                reasons.append(f"RSI en zona neutral-alcista ({rsi:.1f}).")
            elif short_score > long_score:
                short_score += 1
                reasons.append(f"RSI en zona neutral-bajista ({rsi:.1f}).")

        # Pullback y rechazo 1H
        if prev_1h["low"] <= prev_1h["ema20"] and last_1h["close"] > last_1h["open"]:
            long_score += 2
            reasons.append("Pullback a EMA20 con vela alcista de rechazo en 1H.")
        if prev_1h["high"] >= prev_1h["ema20"] and last_1h["close"] < last_1h["open"]:
            short_score += 2
            reasons.append("Pullback a EMA20 con vela bajista de rechazo en 1H.")

        # Volumen 15M
        vol_avg = df_15m["volume"].rolling(20).mean().iloc[-1]
        if last_15m["volume"] > vol_avg:
            reasons.append("Volumen en 15M superior a media de 20 periodos.")
            if long_score > short_score:
                long_score += 1
            elif short_score > long_score:
                short_score += 1

        # Volatilidad
        atr_avg = df_1h["atr"].rolling(30).mean().iloc[-1]
        if last_1h["atr"] > atr_avg * 2:
            return self._no_trade("Volatilidad excesiva (>2x media 30 días).", atr_pct)

        if ctx.has_high_impact_event:
            return self._no_trade("Evento económico de alto impacto cercano.", atr_pct)

        # Modulación por régimen de mercado (opcional: regime=None → sin cambio)
        min_score = 5
        if ctx.regime is not None:
            from trading_bot.features.regime.detector import MarketRegime

            regime = ctx.regime.regime
            if regime == MarketRegime.HIGH_VOL:
                return self._no_trade(
                    f"Régimen de alta volatilidad: {ctx.regime.explanation}", atr_pct
                )
            if regime == MarketRegime.TREND_UP and short_score > long_score:
                return self._no_trade("Short contra régimen alcista bloqueado.", atr_pct)
            if regime == MarketRegime.TREND_DOWN and long_score > short_score:
                return self._no_trade("Long contra régimen bajista bloqueado.", atr_pct)
            if regime == MarketRegime.RANGE:
                min_score = 7  # estrategia de tendencia: en rango exige más confirmaciones
                reasons.append("Régimen de rango: umbral de score elevado.")
            elif regime == MarketRegime.TREND_UP and long_score > short_score:
                long_score += 1
                reasons.append("Régimen alcista alineado (+1).")
            elif regime == MarketRegime.TREND_DOWN and short_score > long_score:
                short_score += 1
                reasons.append("Régimen bajista alineado (+1).")

        if long_score >= min_score and long_score > short_score:
            return self._build_signal(
                TradeDirection.LONG, long_score, short_score, last_1h, atr_pct, reasons, ctx
            )
        if short_score >= min_score and short_score > long_score:
            return self._build_signal(
                TradeDirection.SHORT, short_score, long_score, last_1h, atr_pct, reasons, ctx
            )

        return self._no_trade("Sin alineación suficiente de temporalidades.", atr_pct)

    def _build_signal(
        self,
        direction: TradeDirection,
        score: int,
        opposite: int,
        last_1h: pd.Series,
        atr_pct: Decimal,
        reasons: list[str],
        ctx: MarketContext,
    ) -> StrategyOutput:
        entry = quantize_price(Decimal(str(last_1h["close"])), ctx.symbol)
        atr = Decimal(str(last_1h["atr"]))

        if direction == TradeDirection.LONG:
            stop = quantize_price(entry - atr * Decimal("1.5"), ctx.symbol)
            risk = entry - stop
            tp1 = quantize_price(entry + risk, ctx.symbol)
            tp2 = quantize_price(entry + risk * Decimal("2"), ctx.symbol)
            invalidation = f"Cierre de vela 1H bajo {stop} o ruptura de EMA50 en 4H."
        else:
            stop = quantize_price(entry + atr * Decimal("1.5"), ctx.symbol)
            risk = stop - entry
            tp1 = quantize_price(entry - risk, ctx.symbol)
            tp2 = quantize_price(entry - risk * Decimal("2"), ctx.symbol)
            invalidation = f"Cierre de vela 1H sobre {stop} o ruptura de EMA50 en 4H."

        aligned_tfs = score - opposite
        if aligned_tfs >= 4:
            grade = SetupGrade.A
            confidence = Decimal("85")
        elif aligned_tfs >= 2:
            grade = SetupGrade.B
            confidence = Decimal("65")
        else:
            grade = SetupGrade.C
            confidence = Decimal("40")

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
        from trading_bot.features.signals import indicators as ind

        result = df.copy()
        result["ema20"] = ind.ema(result["close"], 20)
        result["ema50"] = ind.ema(result["close"], 50)
        result["ema200"] = ind.ema(result["close"], 200)
        result["rsi"] = ind.rsi(result["close"], 14)
        result["atr"] = ind.atr(result, 14)
        return result.dropna()
