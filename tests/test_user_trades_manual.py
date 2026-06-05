from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from trading_bot.features.trades.user_routes import _margin_for_leverage, _resolve_leverage
from trading_bot.db.models.account import Account
from trading_bot.db.models.signal import Signal
from trading_bot.db.seed_profiles import ensure_profiles
from trading_bot.core.enums import SignalStatus
from trading_bot.main import app
from trading_bot.db.session import get_db


def test_margin_scales_with_leverage() -> None:
    signal = Signal(
        account_id=1,
        symbol="BTC/USDT",
        direction="LONG",
        primary_timeframe="1h",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        account_balance=Decimal("10"),
        risk_percent=Decimal("1"),
        setup_grade="A",
        position_size=Decimal("100"),
        margin_required=Decimal("10"),
        recommended_leverage=10,
        should_trade=True,
        status=SignalStatus.WATCHING.value,
    )
    assert _margin_for_leverage(signal, 20) == Decimal("5.00")
    assert _margin_for_leverage(signal, 5) == Decimal("20.00")


def test_resolve_leverage_caps_at_profile_max() -> None:
    signal = Signal(
        account_id=1,
        symbol="BTC/USDT",
        direction="LONG",
        primary_timeframe="1h",
        entry_price=Decimal("1"),
        stop_loss=Decimal("0.9"),
        account_balance=Decimal("10"),
        risk_percent=Decimal("1"),
        setup_grade="A",
        recommended_leverage=10,
        should_trade=True,
        status=SignalStatus.WATCHING.value,
    )
    account = Account(
        name="Test",
        profile_type="conservative",
        balance_usdt=Decimal("10"),
        max_leverage=15,
    )
    assert _resolve_leverage(signal, account, 25) == 15
    assert _resolve_leverage(signal, account, None) == 10


@pytest.mark.asyncio
async def test_manual_enter_with_custom_leverage(db_session) -> None:
    from trading_bot.db.models.user_trade import UserTrade

    profiles = await ensure_profiles(db_session)
    profile = profiles[0]
    signal = Signal(
        account_id=profile.id,
        symbol="ETH/USDT",
        direction="LONG",
        primary_timeframe="1h",
        entry_price=Decimal("3000"),
        stop_loss=Decimal("2950"),
        take_profit_1=Decimal("3100"),
        take_profit_2=Decimal("3200"),
        account_balance=profile.balance_usdt,
        risk_percent=Decimal("0.5"),
        setup_grade="A",
        position_size=Decimal("50"),
        margin_required=Decimal("5"),
        recommended_leverage=10,
        risk_usdt=Decimal("0.05"),
        should_trade=True,
        status=SignalStatus.WATCHING.value,
    )
    db_session.add(signal)
    await db_session.commit()
    await db_session.refresh(signal)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/api/v1/user-trades/enter",
            json={
                "signal_id": signal.id,
                "profile_id": profile.id,
                "leverage": 8,
                "manual_only": True,
            },
        )
    app.dependency_overrides.clear()

    assert res.status_code == 200
    data = res.json()
    assert data["leverage"] == 8
    assert data["broker"]["executed"] is False

    trade = await db_session.get(UserTrade, data["trade_id"])
    assert trade is not None
    assert trade.leverage == 8
    assert trade.margin_used == Decimal("6.25")
    assert (trade.notes or "").startswith("manual|")
