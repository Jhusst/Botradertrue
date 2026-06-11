#!/usr/bin/env python3
"""Registra outcomes para señales históricas sin seguimiento."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from trading_bot.db.models.signal import Signal
from trading_bot.db.session import async_session_factory
from trading_bot.features.signals.monitor.price_feed import PriceFeed
from trading_bot.features.signals.outcome_tracker import SignalOutcomeTracker


async def main() -> None:
    feed = PriceFeed(use_live=True)
    async with async_session_factory() as session:
        signals = (
            await session.execute(select(Signal).where(Signal.should_trade.is_(True)))
        ).scalars().all()
        tracker = SignalOutcomeTracker(session)
        created = 0
        for signal in signals:
            await tracker.register_new_signal(signal)
            created += 1
        finalized = await tracker.finalize_untracked_signals(feed)
        await session.commit()
    print(f"Señales registradas: {created} · Finalizadas: {finalized}")


if __name__ == "__main__":
    asyncio.run(main())
