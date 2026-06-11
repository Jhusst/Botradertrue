"""Idempotencia de órdenes: intent persistido antes de la red, sin duplicados."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.db.models.account import Account
from trading_bot.db.models.broker_order import BrokerOrder
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.broker.execution_service import OrderExecutionService


def _fast_settings(**overrides) -> Settings:
    data = get_settings().model_dump()
    data.update(
        sl_placement_max_retries=2,
        sl_placement_backoff_base_seconds=0.001,
        exchange_retry_max_attempts=1,
        **overrides,
    )
    return Settings(**data)


def _mock_broker(settings: Settings) -> BinanceBroker:
    broker = BinanceBroker(settings)
    exchange = MagicMock()
    exchange.amount_to_precision.return_value = "0.002"
    exchange.price_to_precision.side_effect = lambda _s, p: str(p)
    exchange.create_order.return_value = {"id": "E-1", "status": "closed"}
    exchange.fetch_positions.return_value = []
    broker._collector._exchange = exchange
    return broker


async def _make_trade(session: AsyncSession) -> UserTrade:
    account = Account(name="test", balance_usdt=Decimal("500"))
    session.add(account)
    await session.flush()
    trade = UserTrade(
        account_id=account.id,
        symbol="BTC/USDT",
        direction="LONG",
        status="OPEN",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("51000"),
        take_profit_2=Decimal("52000"),
        margin_used=Decimal("10"),
        leverage=5,
        risk_usdt=Decimal("2.5"),
    )
    session.add(trade)
    await session.commit()
    return trade


def test_client_order_id_deterministico() -> None:
    settings = _fast_settings()
    service = OrderExecutionService.__new__(OrderExecutionService)
    service.settings = settings
    assert service.client_order_id(123, BrokerOrder.KIND_ENTRY) == "tbot-123-e"
    assert service.client_order_id(123, BrokerOrder.KIND_SL) == "tbot-123-sl"
    assert service.client_order_id(123, BrokerOrder.KIND_ENTRY) == service.client_order_id(
        123, BrokerOrder.KIND_ENTRY
    )


@pytest.mark.asyncio
async def test_intent_persistido_antes_de_la_red(db_session: AsyncSession) -> None:
    """Si create_order explota, el intent de entrada YA está en DB."""
    settings = _fast_settings()
    broker = _mock_broker(settings)
    broker.exchange.create_order.side_effect = RuntimeError("conexión muerta")
    broker.exchange.fetch_order.side_effect = __import__("ccxt").OrderNotFound("no existe")

    trade = await _make_trade(db_session)
    service = OrderExecutionService(db_session, settings, broker=broker)
    outcome = await service.open_protected_position(
        trade=trade, position_size_usdt=Decimal("100"), leverage=5
    )

    assert outcome.ok is False
    result = await db_session.execute(
        select(BrokerOrder).where(BrokerOrder.client_order_id == f"tbot-{trade.id}-e")
    )
    intent = result.scalar_one()
    assert intent.status == BrokerOrder.STATUS_REJECTED
    assert trade.status == "CANCELLED"


@pytest.mark.asyncio
async def test_reintento_no_duplica_entrada(db_session: AsyncSession) -> None:
    """Con intent ya FILLED/ACKED, una segunda llamada no reenvía la entrada."""
    settings = _fast_settings()
    broker = _mock_broker(settings)
    trade = await _make_trade(db_session)
    service = OrderExecutionService(db_session, settings, broker=broker)

    outcome1 = await service.open_protected_position(
        trade=trade, position_size_usdt=Decimal("100"), leverage=5
    )
    assert outcome1.ok is True
    entry_calls_after_first = sum(
        1 for c in broker.exchange.create_order.call_args_list if c.args[1] == "market"
    )

    outcome2 = await service.open_protected_position(
        trade=trade, position_size_usdt=Decimal("100"), leverage=5
    )
    assert outcome2.ok is True
    entry_calls_after_second = sum(
        1 for c in broker.exchange.create_order.call_args_list if c.args[1] == "market"
    )
    assert entry_calls_after_second == entry_calls_after_first  # ni una entrada más


@pytest.mark.asyncio
async def test_duplicate_client_order_id_se_trata_como_exito(db_session: AsyncSession) -> None:
    settings = _fast_settings()
    broker = _mock_broker(settings)
    broker.exchange.create_order.side_effect = RuntimeError("code=-4015 Duplicate clientOrderId")
    broker.exchange.fetch_order.return_value = {"id": "EXISTING-7", "status": "closed"}

    order = broker.market_order("BTC/USDT", "buy", 0.002, client_order_id="tbot-9-e")
    assert order["id"] == "EXISTING-7"


@pytest.mark.asyncio
async def test_crash_post_envio_se_reanuda_consultando(db_session: AsyncSession) -> None:
    """Intent en SENT (crash post-envío): se consulta el exchange, no se reenvía."""
    settings = _fast_settings()
    broker = _mock_broker(settings)
    trade = await _make_trade(db_session)
    service = OrderExecutionService(db_session, settings, broker=broker)

    # Simular crash: intent quedó SENT
    intent = BrokerOrder(
        user_trade_id=trade.id,
        client_order_id=f"tbot-{trade.id}-e",
        kind=BrokerOrder.KIND_ENTRY,
        symbol=trade.symbol,
        side="buy",
        order_type="market",
        amount=Decimal("0.002"),
        status=BrokerOrder.STATUS_SENT,
    )
    db_session.add(intent)
    await db_session.commit()

    broker.exchange.fetch_order.return_value = {"id": "FOUND-1", "status": "closed"}
    outcome = await service.open_protected_position(
        trade=trade, position_size_usdt=Decimal("100"), leverage=5
    )
    assert outcome.ok is True
    assert outcome.entry_order_id == "FOUND-1"
    # La entrada nunca se reenvió (solo SL/TP usan create_order)
    market_entries = [
        c for c in broker.exchange.create_order.call_args_list if c.args[1] == "market"
    ]
    assert not market_entries
