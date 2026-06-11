from decimal import Decimal

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.enums import SetupGrade, TradeDirection
from trading_bot.schemas.risk import AccountRiskState, RiskAssessment, SetupCandidate


class RiskManager:
    """Valida setups y asigna riesgo permitido según reglas del sistema."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def assess(self, setup: SetupCandidate, account: AccountRiskState) -> RiskAssessment:
        rejection = self._check_hard_blocks(setup, account)
        if rejection:
            return RiskAssessment(
                approved=False,
                direction=TradeDirection.NO_TRADE,
                setup_grade=SetupGrade.C,
                risk_percent=Decimal("0"),
                risk_usdt=Decimal("0"),
                rejection_reason=rejection,
            )

        grade_order = {SetupGrade.A: 1, SetupGrade.B: 2, SetupGrade.C: 3}
        min_grade = SetupGrade(account.min_setup_grade) if account.min_setup_grade in ("A", "B") else SetupGrade.A
        if grade_order.get(setup.setup_grade, 3) > grade_order.get(min_grade, 1):
            return RiskAssessment(
                approved=False,
                direction=TradeDirection.NO_TRADE,
                setup_grade=SetupGrade.C,
                risk_percent=Decimal("0"),
                risk_usdt=Decimal("0"),
                rejection_reason=f"Perfil {account.profile_type} requiere setup grado {min_grade.value} o mejor.",
            )

        if setup.setup_grade == SetupGrade.C:
            return RiskAssessment(
                approved=False,
                direction=TradeDirection.NO_TRADE,
                setup_grade=SetupGrade.C,
                risk_percent=Decimal("0"),
                risk_usdt=Decimal("0"),
                rejection_reason="Setup de baja calidad (grado C). NO TRADE.",
            )

        risk_percent = self._resolve_risk_percent(setup, account)
        risk_usdt = (account.balance_usdt * risk_percent / Decimal("100")).quantize(Decimal("0.01"))

        warnings: list[str] = []
        if setup.has_high_impact_event_nearby:
            warnings.append("Evento económico de alto impacto cercano. Reducir exposición.")
            risk_percent = min(risk_percent, Decimal("0.25"))
            risk_usdt = (account.balance_usdt * risk_percent / Decimal("100")).quantize(Decimal("0.01"))

        if account.current_drawdown_percent >= Decimal("5"):
            warnings.append("Drawdown elevado. Riesgo reducido automáticamente.")
            risk_percent = min(risk_percent, Decimal("0.25"))
            risk_usdt = (account.balance_usdt * risk_percent / Decimal("100")).quantize(Decimal("0.01"))

        if setup.regime in ("RANGE", "HIGH_VOL"):
            warnings.append(f"Régimen {setup.regime}: riesgo reducido automáticamente.")
            risk_percent = min(risk_percent, Decimal("0.25"))
            risk_usdt = (account.balance_usdt * risk_percent / Decimal("100")).quantize(Decimal("0.01"))

        return RiskAssessment(
            approved=True,
            direction=setup.direction,
            setup_grade=setup.setup_grade,
            risk_percent=risk_percent,
            risk_usdt=risk_usdt,
            warnings=warnings,
        )

    def _check_hard_blocks(self, setup: SetupCandidate, account: AccountRiskState) -> str | None:
        if setup.direction == TradeDirection.NO_TRADE:
            return "Dirección NO TRADE."

        if setup.stop_loss <= 0 or setup.entry_price <= 0:
            return "Stop loss o precio de entrada no válido."

        stop_distance = abs(setup.entry_price - setup.stop_loss) / setup.entry_price
        if stop_distance <= Decimal("0"):
            return "Stop loss no es claro o está en el precio de entrada."

        rr = self._calculate_rr(setup)
        if rr < Decimal(str(self.settings.min_risk_reward_ratio)):
            return f"Ratio riesgo/beneficio {rr} menor al mínimo 1:{self.settings.min_risk_reward_ratio}."

        daily_loss_limit = account.balance_usdt * Decimal(str(self.settings.max_daily_loss_percent)) / Decimal("100")
        if account.daily_pnl_usdt <= -daily_loss_limit:
            return f"Pérdida diaria máxima alcanzada ({self.settings.max_daily_loss_percent}%)."

        weekly_loss_limit = account.balance_usdt * Decimal(str(self.settings.max_weekly_loss_percent)) / Decimal("100")
        if account.weekly_pnl_usdt <= -weekly_loss_limit:
            return f"Pérdida semanal máxima alcanzada ({self.settings.max_weekly_loss_percent}%)."

        if account.consecutive_losses >= self.settings.max_consecutive_losses:
            return (
                f"Bloqueado tras {account.consecutive_losses} pérdidas consecutivas. "
                f"Esperar {self.settings.consecutive_loss_cooldown_hours}h."
            )

        if setup.has_high_impact_event_nearby and setup.setup_grade != SetupGrade.A:
            return "Evento económico de alto impacto cercano. Solo setups A permitidos."

        return None

    def _resolve_risk_percent(self, setup: SetupCandidate, account: AccountRiskState) -> Decimal:
        risk_a = account.risk_setup_a or Decimal(str(self.settings.risk_setup_a))
        risk_b = account.risk_setup_b or Decimal(str(self.settings.risk_setup_b))
        if setup.setup_grade == SetupGrade.A:
            if setup.manual_approval:
                return min(Decimal(str(self.settings.risk_setup_a_manual)), risk_a * Decimal("1.5"))
            return risk_a
        if setup.setup_grade == SetupGrade.B:
            return risk_b
        return Decimal("0")

    @staticmethod
    def _calculate_rr(setup: SetupCandidate) -> Decimal:
        risk = abs(setup.entry_price - setup.stop_loss)
        reward = abs(setup.take_profit_2 - setup.entry_price)
        if risk == 0:
            return Decimal("0")
        return (reward / risk).quantize(Decimal("0.01"))
