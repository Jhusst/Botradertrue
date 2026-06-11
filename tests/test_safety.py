"""SafetyService: pausa, kill-switch persistente, flatten-all y endpoints."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.db.init_db import ensure_bot_state
from trading_bot.db.models.account import Account
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.safety.service import SafetyService

from tests.test_protection import FakeNotifier


def _settings(**overrides) -> Settings:
    data = get_settings().model_dump()
    data.update(
        binance_api_key="k",
        binance_api_secret="s",
        exchange_retry_max_attempts=1,
        **overrides,
    )
    return Settings(**data)


def _mock_broker(settings: Settings, positions: list | None = None) -> BinanceBroker:
    broker = BinanceBroker(settings)
    exchange = MagicMock()
    exchange.fetch_positions.return_value = positions or []
    exchange.fetch_balance.return_value = {"info": {"totalMarginBalance": "500"}}
    exchange.create_order.return_value = {"id": "F-1", "status": "closed"}
    broker._collector._exchange = exchange
    return broker


@pytest.mark.asyncio
async def test_pause_y_resume_persisten(db_session: AsyncSession) -> None:
    settings = _settings()
    service = SafetyService(db_session, settings, broker=_mock_broker(settings), notifier=FakeNotifier())

    state = await service.pause_entries("test", by="pytest")
    assert state.entries_paused is True

    # "Reinicio": releer desde DB
    fresh = await ensure_bot_state(db_session)
    assert fresh.entries_paused is True

    state = await service.resume_entries(by="pytest")
    assert state.entries_paused is False


@pytest.mark.asyncio
async def test_kill_switch_no_se_rearma_con_resume(db_session: AsyncSession) -> None:
    settings = _settings()
    service = SafetyService(db_session, settings, broker=_mock_broker(settings), notifier=FakeNotifier())
    await service.engage_kill_switch("prueba", flatten=False, by="pytest")

    state = await ensure_bot_state(db_session)
    assert state.kill_switch_engaged is True

    await service.resume_entries(by="pytest")
    state = await ensure_bot_state(db_session)
    assert state.kill_switch_engaged is True  # resume NO rearma

    await service.arm(by="pytest")
    state = await ensure_bot_state(db_session)
    assert state.kill_switch_engaged is False


@pytest.mark.asyncio
async def test_flatten_all_cierra_posiciones_y_trades(db_session: AsyncSession) -> None:
    settings = _settings()
    positions = [
        {"symbol": "BTC/USDT:USDT", "side": "long", "contracts": "0.002"},
        {"symbol": "ETH/USDT:USDT", "side": "short", "contracts": "1.0"},
    ]
    broker = _mock_broker(settings, positions)
    account = Account(name="safety", balance_usdt=Decimal("500"))
    db_session.add(account)
    await db_session.flush()
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
    )
    db_session.add(trade)
    await db_session.commit()

    service = SafetyService(db_session, settings, broker=broker, notifier=FakeNotifier())
    result = await service.flatten_all("emergencia", by="pytest")

    assert result.ok is True
    assert set(result.closed_symbols) == {"BTC/USDT:USDT", "ETH/USDT:USDT"}
    assert result.db_trades_closed == 1
    assert trade.status == "CLOSED"
    assert broker.exchange.cancel_all_orders.call_count == 2


@pytest.mark.asyncio
async def test_endpoint_flatten_exige_confirmacion(client: AsyncClient) -> None:
    response = await client.post("/api/v1/safety/flatten-all", json={"confirm": "no"})
    assert response.status_code == 400

    response = await client.post("/api/v1/safety/kill", json={"confirm": "nope"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_endpoint_status(client: AsyncClient) -> None:
    response = await client.get("/api/v1/safety/status")
    assert response.status_code == 200
    body = response.json()
    assert "kill_switch_engaged" in body
    assert "circuit_breaker" in body
