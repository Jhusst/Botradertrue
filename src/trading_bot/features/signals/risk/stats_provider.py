"""Estadísticas de trades cerrados (paper + reales) para alimentar a Kelly."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.db.models.trade import PaperTrade
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.signals.risk.kelly import KellyCalculator, TradeStats


class TradeStatsProvider:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def get_stats(self, session: AsyncSession, lookback: int | None = None) -> TradeStats | None:
        """R-multiples de los últimos N trades cerrados (paper + user)."""
        lookback = lookback or self.settings.kelly_lookback_trades
        r_multiples: list[float] = []

        user_result = await session.execute(
            select(UserTrade.pnl_usdt, UserTrade.risk_usdt)
            .where(UserTrade.status == "CLOSED", UserTrade.pnl_usdt.is_not(None))
            .order_by(UserTrade.closed_at.desc())
            .limit(lookback)
        )
        for pnl, risk in user_result.all():
            if risk and risk > 0:
                r_multiples.append(float(pnl) / float(risk))

        if len(r_multiples) < lookback:
            paper_result = await session.execute(
                select(PaperTrade.pnl_usdt, PaperTrade.risk_usdt)
                .where(PaperTrade.status.in_(["CLOSED", "STOPPED", "TP2_HIT"]))
                .where(PaperTrade.pnl_usdt.is_not(None))
                .order_by(PaperTrade.closed_at.desc())
                .limit(lookback - len(r_multiples))
            )
            for pnl, risk in paper_result.all():
                if risk and risk > 0:
                    r_multiples.append(float(pnl) / float(risk))

        return KellyCalculator.stats_from_r_multiples(
            r_multiples, min_trades=self.settings.kelly_min_trades
        )
