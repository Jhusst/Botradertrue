from decimal import Decimal

from trading_bot.config.settings import get_settings
from trading_bot.core.asset_catalog import get_asset_info
from trading_bot.core.enums import SetupGrade, TradeDirection
from trading_bot.features.signals.risk import KellyCalculator, PositionSizer, RiskManager, TradeStats
from trading_bot.features.signals.strategies.precious_metals_mvp import PreciousMetalsMVPStrategy
from trading_bot.features.signals.strategies.trend_pullback_mvp import (
    MarketContext,
    StrategyOutput,
    TrendPullbackMVPStrategy,
)
from trading_bot.schemas.risk import AccountRiskState, PositionSizingInput, SetupCandidate
from trading_bot.schemas.signal import SignalCreate


class SignalGenerator:
    """Orquesta estrategia → riesgo → (Kelly) → sizing → señal final."""

    def __init__(self) -> None:
        self.crypto_strategy = TrendPullbackMVPStrategy()
        self.metals_strategy = PreciousMetalsMVPStrategy()
        self.risk_manager = RiskManager()
        self.position_sizer = PositionSizer()
        self.kelly = KellyCalculator()

    def _pick_strategy(self, symbol: str):
        asset = get_asset_info(symbol)
        if asset.asset_class == "precious_metal":
            return self.metals_strategy
        return self.crypto_strategy

    def generate(
        self,
        ctx: MarketContext,
        account: AccountRiskState,
        *,
        trade_stats: TradeStats | None = None,
        ml_probability: float | None = None,
    ) -> SignalCreate:
        strategy = self._pick_strategy(ctx.symbol)
        strategy_out = strategy.analyze(ctx)

        if strategy_out.direction == TradeDirection.NO_TRADE or strategy_out.setup_grade == SetupGrade.C:
            return self._build_no_trade(ctx.symbol, strategy_out, account, "Setup no cumple criterios mínimos.")

        assert strategy_out.entry_price and strategy_out.stop_loss
        assert strategy_out.take_profit_1 and strategy_out.take_profit_2

        setup = SetupCandidate(
            symbol=ctx.symbol,
            direction=strategy_out.direction,
            primary_timeframe=strategy_out.primary_timeframe,
            entry_price=strategy_out.entry_price,
            stop_loss=strategy_out.stop_loss,
            take_profit_1=strategy_out.take_profit_1,
            take_profit_2=strategy_out.take_profit_2,
            setup_grade=strategy_out.setup_grade,
            confidence_score=strategy_out.confidence_score,
            technical_explanation=strategy_out.technical_explanation,
            invalidation_conditions=strategy_out.invalidation_conditions,
            atr_percent=strategy_out.atr_percent,
            has_high_impact_event_nearby=ctx.has_high_impact_event,
            regime=ctx.regime.regime.value if ctx.regime else None,
        )

        assessment = self.risk_manager.assess(setup, account)
        if not assessment.approved:
            return self._build_no_trade(
                ctx.symbol, strategy_out, account, assessment.rejection_reason or "Rechazado por riesgo."
            )

        # Kelly fraccionado: SOLO reduce el riesgo ya aprobado, nunca lo sube
        settings = get_settings()
        if settings.kelly_enabled and trade_stats is not None:
            kelly_risk = self.kelly.risk_percent(trade_stats, ml_probability)
            if kelly_risk is not None and kelly_risk < assessment.risk_percent:
                assessment = assessment.model_copy(
                    update={
                        "risk_percent": kelly_risk,
                        "risk_usdt": (account.balance_usdt * kelly_risk / Decimal("100")).quantize(
                            Decimal("0.01")
                        ),
                        "warnings": [*assessment.warnings, f"Kelly fraccionado: riesgo {kelly_risk}%."],
                    }
                )

        asset = get_asset_info(ctx.symbol)
        sizing = self.position_sizer.calculate(
            PositionSizingInput(
                balance_usdt=account.balance_usdt,
                risk_percent=assessment.risk_percent,
                entry_price=strategy_out.entry_price,
                stop_loss=strategy_out.stop_loss,
                take_profit_1=strategy_out.take_profit_1,
                take_profit_2=strategy_out.take_profit_2,
                direction=strategy_out.direction,
                setup_grade=strategy_out.setup_grade,
                primary_timeframe=strategy_out.primary_timeframe,
                atr_percent=strategy_out.atr_percent,
                drawdown_percent=account.current_drawdown_percent,
                has_high_impact_event_nearby=ctx.has_high_impact_event,
                asset_class=asset.asset_class,
                max_leverage_cap=account.max_leverage,
            )
        )
        if account.max_leverage and sizing.recommended_leverage > account.max_leverage:
            sizing = sizing.model_copy(update={"recommended_leverage": account.max_leverage})

        explanation = strategy_out.technical_explanation
        if assessment.warnings:
            explanation += " | ADVERTENCIAS: " + "; ".join(assessment.warnings)

        return SignalCreate(
            symbol=ctx.symbol,
            direction=strategy_out.direction,
            primary_timeframe=strategy_out.primary_timeframe,
            entry_price=strategy_out.entry_price,
            stop_loss=strategy_out.stop_loss,
            take_profit_1=strategy_out.take_profit_1,
            take_profit_2=strategy_out.take_profit_2,
            risk_reward_ratio=sizing.risk_reward_ratio,
            account_balance=account.balance_usdt,
            risk_percent=assessment.risk_percent,
            risk_usdt=sizing.risk_usdt,
            recommended_capital_usdt=sizing.recommended_capital_usdt,
            recommended_leverage=sizing.recommended_leverage,
            max_loss_usdt=sizing.max_loss_usdt,
            estimated_gain_tp1_usdt=sizing.estimated_gain_tp1_usdt,
            estimated_gain_tp2_usdt=sizing.estimated_gain_tp2_usdt,
            position_size=sizing.position_size_usdt,
            margin_required=sizing.margin_required_usdt,
            stop_distance_percent=sizing.stop_distance_percent,
            tp1_distance_percent=sizing.tp1_distance_percent,
            tp2_distance_percent=sizing.tp2_distance_percent,
            liquidation_price=sizing.liquidation_price,
            setup_grade=strategy_out.setup_grade,
            confidence_score=strategy_out.confidence_score,
            technical_explanation=explanation,
            invalidation_conditions=strategy_out.invalidation_conditions,
            should_trade=True,
            strategy_name=strategy.STRATEGY_NAME,
        )

    def _build_no_trade(
        self, symbol: str, out: StrategyOutput, account: AccountRiskState, reason: str
    ) -> SignalCreate:
        return SignalCreate(
            symbol=symbol,
            direction=TradeDirection.NO_TRADE,
            primary_timeframe=out.primary_timeframe,
            account_balance=account.balance_usdt,
            risk_percent=Decimal("0"),
            setup_grade=SetupGrade.C,
            confidence_score=out.confidence_score,
            technical_explanation=out.technical_explanation,
            invalidation_conditions=out.invalidation_conditions,
            should_trade=False,
            rejection_reason=reason,
            strategy_name=self._pick_strategy(symbol).STRATEGY_NAME,
        )
