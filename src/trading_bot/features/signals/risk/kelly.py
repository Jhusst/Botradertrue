"""Kelly fraccionado: dimensiona el riesgo según el edge MEDIDO.

Regla de oro: Kelly SOLO REDUCE el riesgo que el RiskManager ya aprobó,
nunca lo aumenta. Con <kelly_min_trades de historial no opina.

f* = W - (1-W) / R   donde W = win rate, R = avg_win_R / avg_loss_R
riesgo% = clamp(f* × fraction × 100, floor, cap)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading_bot.config.settings import Settings, get_settings


@dataclass(frozen=True)
class TradeStats:
    n_trades: int
    win_rate: float        # [0, 1]
    avg_win_r: float       # R-multiple medio de ganadores (>0)
    avg_loss_r: float      # R-multiple medio de perdedores en valor absoluto (>0)


class KellyCalculator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def fraction(self) -> float:
        return self.settings.kelly_fraction

    def kelly_fraction(self, stats: TradeStats) -> float:
        """f* de Kelly clásico. 0 si no hay edge (f* negativo)."""
        if stats.avg_loss_r <= 0 or stats.avg_win_r <= 0:
            return 0.0
        payoff = stats.avg_win_r / stats.avg_loss_r
        f_star = stats.win_rate - (1 - stats.win_rate) / payoff
        return max(0.0, f_star)

    def risk_percent(
        self, stats: TradeStats | None, ml_probability: float | None = None
    ) -> Decimal | None:
        """Riesgo % sugerido por Kelly fraccionado, o None si no hay datos suficientes."""
        if stats is None or stats.n_trades < self.settings.kelly_min_trades:
            return None
        effective = stats
        if ml_probability is not None and 0.0 < ml_probability < 1.0:
            # Kelly condicionado por la convicción del modelo en ESTE trade
            effective = TradeStats(
                n_trades=stats.n_trades,
                win_rate=ml_probability,
                avg_win_r=stats.avg_win_r,
                avg_loss_r=stats.avg_loss_r,
            )
        f_star = self.kelly_fraction(effective)
        raw = f_star * self.fraction * 100
        floor = self.settings.kelly_floor_risk_percent
        cap = self.settings.kelly_cap_risk_percent
        if raw <= 0:
            return Decimal(str(floor))
        return Decimal(str(round(min(max(raw, floor), cap), 4)))

    @staticmethod
    def stats_from_r_multiples(r_multiples: list[float], min_trades: int = 20) -> TradeStats | None:
        if len(r_multiples) < min_trades:
            return None
        wins = [r for r in r_multiples if r > 0]
        losses = [abs(r) for r in r_multiples if r <= 0]
        if not wins or not losses:
            return None
        return TradeStats(
            n_trades=len(r_multiples),
            win_rate=len(wins) / len(r_multiples),
            avg_win_r=sum(wins) / len(wins),
            avg_loss_r=sum(losses) / len(losses),
        )
