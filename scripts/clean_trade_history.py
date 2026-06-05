#!/usr/bin/env python3
"""Borra historial de trades y alertas; conserva perfiles, señales y config."""
from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import delete, func, select, update

from trading_bot.db.models.account import Account
from trading_bot.db.models.alert_log import AlertLog
from trading_bot.db.models.trade import PaperTrade
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.db.session import async_session_factory


async def main() -> None:
    async with async_session_factory() as session:
        user_count = (await session.execute(select(func.count()).select_from(UserTrade))).scalar() or 0
        paper_count = (await session.execute(select(func.count()).select_from(PaperTrade))).scalar() or 0
        alert_count = (await session.execute(select(func.count()).select_from(AlertLog))).scalar() or 0

        await session.execute(delete(UserTrade))
        await session.execute(delete(PaperTrade))
        await session.execute(delete(AlertLog))
        await session.execute(
            update(Account).values(
                daily_pnl_usdt=Decimal("0"),
                weekly_pnl_usdt=Decimal("0"),
                consecutive_losses=0,
            )
        )
        await session.commit()

    print(f"Eliminados: {user_count} user_trades, {paper_count} paper_trades, {alert_count} alert_logs")
    print("P&L y racha de pérdidas de perfiles reiniciados. Señales y cuentas conservadas.")


if __name__ == "__main__":
    asyncio.run(main())
