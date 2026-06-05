from decimal import Decimal

import pandas as pd

from trading_bot.core.asset_catalog import get_asset_info, quantize_price
from trading_bot.core.enums import SetupGrade, TradeDirection
from trading_bot.modules.strategy_engine.trend_pullback_mvp import MarketContext, StrategyOutput
from trading_bot.modules.strategy_engine.trend_pullback_mvp import TrendPullbackMVPStrategy


class PreciousMetalsMVPStrategy(TrendPullbackMVPStrategy):
    """Estrategia para oro/plata: tendencias más suaves, umbrales adaptados.

    Los metales suelen moverse con menos ruido que cripto; se prioriza la
    tendencia en 4H y pullbacks limpios en 1H con confirmación de volumen.
    """

    STRATEGY_NAME = "PreciousMetalsMVP"
    MIN_SCORE = 4
    ATR_STOP_MULT = Decimal("1.2")
    MAX_VOLATILITY_MULT = Decimal("2.5")

    def analyze(self, ctx: MarketContext) -> StrategyOutput:
        df_4h = self._add_indicators(ctx.df_4h)
        df_1h = self._add_indicators(ctx.df_1h)
        df_15m = self._add_indicators(ctx.df_15m)

        if len(df_4h) < 200 or len(df_1h) < 50 or len(df_15m) < 30:
            return self._no_trade("Datos insuficientes para análisis.", symbol=ctx.symbol)

        last_4h = df_4h.iloc[-1]
        last_1h = df_1h.iloc[-1]
        last_15m = df_15m.iloc[-1]
        prev_1h = df_1h.iloc[-2]

        atr_pct = Decimal(str((last_1h["atr"] / last_1h["close"] * 100).round(4)))
        asset = get_asset_info(ctx.symbol)

        long_score = 0
        short_score = 0
        reasons: list[str] = [f"Activo: {asset.display_name}."]

        if last_4h["close"] > last_4h["ema200"] and last_4h["ema50"] > last_4h["ema200"]:
            long_score += 3
            reasons.append("Tendencia alcista clara en 4H (precio y EMA50 sobre EMA200).")
        elif last_4h["close"] < last_4h["ema200"] and last_4h["ema50"] < last_4h["ema200"]:
            short_score += 3
            reasons.append("Tendencia bajista clara en 4H (precio y EMA50 bajo EMA200).")
        elif last_4h["close"] > last_4h["ema200"]:
            long_score += 2
            reasons.append("Precio sobre EMA200 en 4H.")
        elif last_4h["close"] < last_4h["ema200"]:
            short_score += 2
            reasons.append("Precio bajo EMA200 en 4H.")

        if last_1h["ema20"] > last_1h["ema50"]:
            long_score += 1
        elif last_1h["ema20"] < last_1h["ema50"]:
            short_score += 1

        rsi = last_1h["rsi"]
        if 42 <= rsi <= 58:
            if long_score > short_score:
                long_score += 1
                reasons.append(f"RSI en zona de valor ({rsi:.1f}).")
            elif short_score > long_score:
                short_score += 1
                reasons.append(f"RSI en zona de valor ({rsi:.1f}).")

        if prev_1h["low"] <= prev_1h["ema20"] and last_1h["close"] > last_1h["open"]:
            long_score += 2
            reasons.append("Pullback a EMA20 con rechazo alcista en 1H.")
        if prev_1h["high"] >= prev_1h["ema20"] and last_1h["close"] < last_1h["open"]:
            short_score += 2
            reasons.append("Pullback a EMA20 con rechazo bajista en 1H.")

        vol_avg = df_15m["volume"].rolling(20).mean().iloc[-1]
        if last_15m["volume"] > vol_avg:
            reasons.append("Volumen en 15M por encima de la media.")
            if long_score > short_score:
                long_score += 1
            elif short_score > long_score:
                short_score += 1

        atr_avg = df_1h["atr"].rolling(30).mean().iloc[-1]
        if last_1h["atr"] > atr_avg * float(self.MAX_VOLATILITY_MULT):
            return self._no_trade(
                f"Volatilidad excesiva (>{self.MAX_VOLATILITY_MULT}x media).", atr_pct, ctx.symbol
            )

        if ctx.has_high_impact_event:
            return self._no_trade("Evento económico de alto impacto cercano.", atr_pct, ctx.symbol)

        if long_score >= self.MIN_SCORE and long_score > short_score:
            return self._build_metals_signal(
                TradeDirection.LONG, long_score, short_score, last_1h, atr_pct, reasons, ctx
            )
        if short_score >= self.MIN_SCORE and short_score > long_score:
            return self._build_metals_signal(
                TradeDirection.SHORT, short_score, long_score, last_1h, atr_pct, reasons, ctx
            )

        return self._no_trade("Sin alineación suficiente para metales.", atr_pct, ctx.symbol)

    def _build_metals_signal(
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
            stop = quantize_price(entry - atr * self.ATR_STOP_MULT, ctx.symbol)
            risk = entry - stop
            tp1 = quantize_price(entry + risk, ctx.symbol)
            tp2 = quantize_price(entry + risk * Decimal("2"), ctx.symbol)
            invalidation = f"Cierre 1H bajo {stop} o pérdida de EMA50 en 4H."
        else:
            stop = quantize_price(entry + atr * self.ATR_STOP_MULT, ctx.symbol)
            risk = stop - entry
            tp1 = quantize_price(entry - risk, ctx.symbol)
            tp2 = quantize_price(entry - risk * Decimal("2"), ctx.symbol)
            invalidation = f"Cierre 1H sobre {stop} o pérdida de EMA50 en 4H."

        aligned = score - opposite
        if aligned >= 3:
            grade = SetupGrade.A
            confidence = Decimal("80")
        elif aligned >= 2:
            grade = SetupGrade.B
            confidence = Decimal("68")
        else:
            grade = SetupGrade.C
            confidence = Decimal("45")

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

    def _no_trade(
        self, reason: str, atr_pct: Decimal | None = None, symbol: str = "BTC/USDT"
    ) -> StrategyOutput:
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
