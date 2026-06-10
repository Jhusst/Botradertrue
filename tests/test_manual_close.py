"""Cierre manual de trades: endpoint close-market."""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.db.models.account import Account
from trading_bot.db.models.user_trade import UserTrade


async def _make_trade(session: AsyncSession, notes: str | None = None) -> UserTrade:
    account = Account(name="manual", balance_usdt=Decimal("500"))
    session.add(account)
    await session.flush()
    trade = UserTrade(
        account_id=account.id,
        symbol="BTC/USDT",
        direction="LONG",
        status="OPEN",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        margin_used=Decimal("10"),
        leverage=5,
        risk_usdt=Decimal("2.5"),
        notes=notes,
    )
    session.add(trade)
    await session.commit()
    return trade


@pytest.mark.asyncio
async def test_close_market_inexistente_404(client: AsyncClient) -> None:
    response = await client.post("/api/v1/user-trades/99999/close-market")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_close_market_sin_broker_exige_camino_clasico(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    trade = await _make_trade(db_session, notes="manual|lev=5x|bitunix")
    response = await client.post(f"/api/v1/user-trades/{trade.id}/close-market")
    assert response.status_code == 400
    assert "close" in response.json()["detail"]


@pytest.mark.asyncio
async def test_close_clasico_sigue_funcionando(client: AsyncClient, db_session: AsyncSession) -> None:
    trade = await _make_trade(db_session, notes="manual|lev=5x|bitunix")
    response = await client.post(
        f"/api/v1/user-trades/{trade.id}/close",
        json={"exit_price": "51000", "close_reason": "MANUAL"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
