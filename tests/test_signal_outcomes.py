from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from trading_bot.core.enums import TradeDirection
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.signal_outcome import SignalOutcome
from trading_bot.features.signals.outcome_tracker import SignalOutcomeTracker


@pytest.mark.asyncio
async def test_track_price_tp2_short(db_session) -> None:
    signal = Signal(
        account_id=1,
        symbol="BTC/USDT",
        direction=TradeDirection.SHORT.value,
        primary_timeframe="1h",
        entry_price=Decimal("60000"),
        stop_loss=Decimal("61000"),
        take_profit_1=Decimal("59000"),
        take_profit_2=Decimal("58000"),
        account_balance=Decimal("30"),
        risk_percent=Decimal("0.75"),
        setup_grade="A",
        should_trade=True,
        status="ACTIVE",
    )
    db_session.add(signal)
    await db_session.flush()

    tracker = SignalOutcomeTracker(db_session)
    await tracker.register_skip(signal, reason="AI_BLOCKED", entry_touched=True)
    await tracker.track_price(signal, Decimal("60100"), entry_touched=True)
    hit = await tracker.track_price(signal, Decimal("57900"), entry_touched=True)
    assert hit == "TP2"

    result = await db_session.execute(
        select(SignalOutcome).where(SignalOutcome.signal_id == signal.id)
    )
    row = result.scalar_one()
    assert row.executed is False
    assert row.outcome == "TP2"
    assert row.skip_reason == "AI_BLOCKED"


@pytest.mark.asyncio
async def test_outcomes_api(client: AsyncClient) -> None:
    response = await client.get("/api/v1/signal-outcomes?limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "outcomes" in data
