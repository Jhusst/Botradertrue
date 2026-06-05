from decimal import Decimal

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.enums import SetupGrade, TradeDirection
from trading_bot.schemas.risk import PositionSizingInput, PositionSizingResult


class PositionSizer:
    """Calcula tamaño de posición, margen, apalancamiento y liquidación estimada."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def calculate(self, data: PositionSizingInput) -> PositionSizingResult:
        risk_usdt = (data.balance_usdt * data.risk_percent / Decimal("100")).quantize(Decimal("0.01"))
        stop_distance = abs(data.entry_price - data.stop_loss)
        stop_distance_percent = (stop_distance / data.entry_price * Decimal("100")).quantize(Decimal("0.0001"))

        if stop_distance == 0:
            raise ValueError("Distancia al stop loss es cero.")

        position_size = (risk_usdt / stop_distance * data.entry_price).quantize(Decimal("0.01"))

        leverage = self._calculate_leverage(data, stop_distance_percent)
        if data.max_leverage_cap:
            leverage = min(leverage, data.max_leverage_cap)
        margin_required = (position_size / Decimal(leverage)).quantize(Decimal("0.01"))

        tp1_distance = abs(data.take_profit_1 - data.entry_price)
        tp2_distance = abs(data.take_profit_2 - data.entry_price)
        tp1_distance_percent = (tp1_distance / data.entry_price * Decimal("100")).quantize(Decimal("0.0001"))
        tp2_distance_percent = (tp2_distance / data.entry_price * Decimal("100")).quantize(Decimal("0.0001"))

        risk_reward_ratio = (tp2_distance / stop_distance).quantize(Decimal("0.01"))

        gain_tp1 = (position_size * tp1_distance / data.entry_price).quantize(Decimal("0.01"))
        gain_tp2 = (position_size * tp2_distance / data.entry_price).quantize(Decimal("0.01"))

        liquidation = self._estimate_liquidation(data.entry_price, leverage, data.direction)

        return PositionSizingResult(
            position_size_usdt=position_size,
            margin_required_usdt=margin_required,
            recommended_leverage=leverage,
            risk_usdt=risk_usdt,
            max_loss_usdt=risk_usdt,
            estimated_gain_tp1_usdt=gain_tp1,
            estimated_gain_tp2_usdt=gain_tp2,
            stop_distance_percent=stop_distance_percent,
            tp1_distance_percent=tp1_distance_percent,
            tp2_distance_percent=tp2_distance_percent,
            risk_reward_ratio=risk_reward_ratio,
            liquidation_price=liquidation,
            recommended_capital_usdt=margin_required,
        )

    def _calculate_leverage(self, data: PositionSizingInput, stop_distance_percent: Decimal) -> int:
        """Apalancamiento dinámico basado en volatilidad, stop, TF, grado y drawdown."""
        if data.asset_class == "precious_metal":
            base = Decimal("5")
        else:
            base = Decimal("10")

        # Stop más amplio → menos apalancamiento
        if stop_distance_percent > Decimal("3"):
            base -= Decimal("1.5")
        elif stop_distance_percent > Decimal("2"):
            base -= Decimal("1")
        elif stop_distance_percent < Decimal("0.5"):
            base -= Decimal("0.5")

        # Volatilidad (ATR%)
        if data.atr_percent:
            if data.atr_percent > Decimal("4"):
                base -= Decimal("1.5")
            elif data.atr_percent > Decimal("2.5"):
                base -= Decimal("0.5")
            elif data.atr_percent < Decimal("1"):
                base += Decimal("0.5")

        # Temporalidad
        tf_adjustments = {"15m": Decimal("-1"), "1h": Decimal("0"), "4h": Decimal("0.5"), "1d": Decimal("1")}
        base += tf_adjustments.get(data.primary_timeframe, Decimal("0"))

        # Grado de setup
        grade_adj = {SetupGrade.A: Decimal("1"), SetupGrade.B: Decimal("0"), SetupGrade.C: Decimal("-2")}
        base += grade_adj.get(data.setup_grade, Decimal("0"))

        # Drawdown actual
        if data.drawdown_percent >= Decimal("5"):
            base -= Decimal("1.5")
        elif data.drawdown_percent >= Decimal("3"):
            base -= Decimal("0.5")

        # Eventos económicos
        if data.has_high_impact_event_nearby:
            base -= Decimal("1")

        # Liquidez
        if data.liquidity_score < Decimal("0.5"):
            base -= Decimal("1")

        leverage = int(max(base, Decimal(str(self.settings.min_leverage))))
        return min(leverage, self.settings.max_leverage)

    @staticmethod
    def _estimate_liquidation(
        entry: Decimal, leverage: int, direction: TradeDirection
    ) -> Decimal | None:
        """Estimación simplificada de precio de liquidación (mantenimiento ~0.5%)."""
        if leverage <= 0:
            return None
        maintenance_margin = Decimal("0.005")
        move_fraction = (Decimal("1") / Decimal(leverage)) - maintenance_margin
        if move_fraction <= 0:
            return None
        if direction == TradeDirection.LONG:
            return (entry * (Decimal("1") - move_fraction)).quantize(Decimal("0.01"))
        if direction == TradeDirection.SHORT:
            return (entry * (Decimal("1") + move_fraction)).quantize(Decimal("0.01"))
        return None
