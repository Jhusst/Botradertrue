"""Protección garantizada: SL con retry, flatten si falla, kill-switch como última línea."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.db.init_db import ensure_bot_state
from trading_bot.db.models.account import Account
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.broker.execution_service import OrderExecutionService


class FakeNotifier:
    def __init__(self) -> None:
        self.alerts: list[dict] = []

    @property
    def is_configured(self) -> bool:
        return True

    async def send_alert(self, alert_type, symbol, direction, **kwargs) -> bool:
        self.alerts.append({"type": alert_type, "symbol": symbol, **kwargs})
        return True

    async def send_raw(self, message: str, urgent: bool = False) -> bool:
        self.alerts.append({"raw": message, "urgent": urgent})
        return True


def _fast_settings(**overrides) -> Settings:
    data = get_settings().model_dump()
    defaults = {
        "sl_placement_max_retries": 3,
        "sl_placement_backoff_base_seconds": 0.001,
        "exchange_retry_max_attempts": 1,
        "flatten_on_protection_failure": True,
    }
    data.update({**defaults, **overrides})
    return Settings(**data)


def _mock_broker(settings: Settings) -> BinanceBroker:
    broker = BinanceBroker(settings)
    exchange = MagicMock()
    exchange.amount_to_precision.return_value = "0.002"
    exchange.price_to_precision.side_effect = lambda _s, p: str(p)
    exchange.create_order.return_value = {"id": "OK-1", "status": "closed"}
    exchange.fetch_positions.return_value = [
        {"symbol": "BTC/USDT:USDT", "side": "long", "contracts": "0.002"}
    ]
    broker._collector._exchange = exchange
    return broker


async def _make_trade(session: AsyncSession) -> UserTrade:
    account = Account(name="prot", balance_usdt=Decimal("500"))
    session.add(account)
    await session.flush()
    trade = UserTrade(
        account_id=account.id,
        symbol="BTC/USDT",
        direction="LONG",
        status="OPEN",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_2=Decimal("52000"),
        margin_used=Decimal("10"),
        leverage=5,
        risk_usdt=Decimal("2.5"),
    )
    session.add(trade)
    await session.commit()
    return trade


def _sl_calls(exchange: MagicMock) -> list:
    return [c for c in exchange.create_order.call_args_list if c.args[1] == "stop_market"]


@pytest.mark.asyncio
async def test_sl_reintenta_y_protege(db_session: AsyncSession) -> None:
    """SL falla 2 veces y entra a la 3.ª: posición queda protegida."""
    settings = _fast_settings()
    broker = _mock_broker(settings)
    trade = await _make_trade(db_session)

    failures = {"n": 0}
    original_return = {"id": "SL-1", "status": "open"}

    def create_order_side_effect(symbol, order_type, side, amount, price, params=None):
        if order_type == "stop_market":
            failures["n"] += 1
            if failures["n"] < 3:
                raise RuntimeError("red caída")
            return original_return
        return {"id": "OK-1", "status": "closed"}

    broker.exchange.create_order.side_effect = create_order_side_effect
    service = OrderExecutionService(db_session, settings, broker=broker, notifier=FakeNotifier())
    outcome = await service.open_protected_position(
        trade=trade, position_size_usdt=Decimal("100"), leverage=5
    )
    assert outcome.ok is True
    assert outcome.sl_ok is True
    assert failures["n"] == 3


@pytest.mark.asyncio
async def test_sl_imposible_aplana_y_alerta(db_session: AsyncSession) -> None:
    """SL falla siempre → flatten inmediato + alerta crítica + trade CLOSED."""
    settings = _fast_settings()
    broker = _mock_broker(settings)
    trade = await _make_trade(db_session)
    notifier = FakeNotifier()

    def create_order_side_effect(symbol, order_type, side, amount, price, params=None):
        if order_type == "stop_market":
            raise RuntimeError("SL imposible")
        return {"id": "OK-1", "status": "closed"}

    broker.exchange.create_order.side_effect = create_order_side_effect
    broker.exchange.fetch_order.side_effect = __import__("ccxt").OrderNotFound("no")
    service = OrderExecutionService(db_session, settings, broker=broker, notifier=notifier)
    outcome = await service.open_protected_position(
        trade=trade, position_size_usdt=Decimal("100"), leverage=5
    )

    assert outcome.ok is False
    assert outcome.flattened is True
    assert trade.status == "CLOSED"
    assert trade.close_reason == "PROTECTION_FAILED"
    broker.exchange.cancel_all_orders.assert_called()
    assert any("POSICIÓN CERRADA" in str(a) or a.get("type") for a in notifier.alerts)


@pytest.mark.asyncio
async def test_flatten_imposible_activa_kill_switch(db_session: AsyncSession) -> None:
    """SL y flatten fallan → kill-switch automático persistido en BotState."""
    settings = _fast_settings(sl_placement_max_retries=1)
    broker = _mock_broker(settings)
    trade = await _make_trade(db_session)
    notifier = FakeNotifier()

    def create_order_side_effect(symbol, order_type, side, amount, price, params=None):
        if order_type == "stop_market":
            raise RuntimeError("SL imposible")
        if params and params.get("reduceOnly"):
            raise RuntimeError("flatten imposible")
        return {"id": "OK-1", "status": "closed"}

    broker.exchange.create_order.side_effect = create_order_side_effect
    broker.exchange.fetch_order.side_effect = __import__("ccxt").OrderNotFound("no")
    service = OrderExecutionService(db_session, settings, broker=broker, notifier=notifier)
    outcome = await service.open_protected_position(
        trade=trade, position_size_usdt=Decimal("100"), leverage=5
    )

    assert outcome.ok is False
    assert outcome.flattened is False
    state = await ensure_bot_state(db_session)
    assert state.kill_switch_engaged is True
    assert "INTERVENCIÓN MANUAL" in str(notifier.alerts)


@pytest.mark.asyncio
async def test_tp_fallido_no_aplana_si_hay_sl(db_session: AsyncSession) -> None:
    """TP falla pero el SL está puesto: posición se mantiene, solo alerta."""
    settings = _fast_settings()
    broker = _mock_broker(settings)
    trade = await _make_trade(db_session)
    notifier = FakeNotifier()

    def create_order_side_effect(symbol, order_type, side, amount, price, params=None):
        if order_type == "take_profit_market":
            raise RuntimeError("TP rechazado")
        return {"id": "OK-1", "status": "open"}

    broker.exchange.create_order.side_effect = create_order_side_effect
    broker.exchange.fetch_order.side_effect = __import__("ccxt").OrderNotFound("no")
    service = OrderExecutionService(db_session, settings, broker=broker, notifier=notifier)
    outcome = await service.open_protected_position(
        trade=trade, position_size_usdt=Decimal("100"), leverage=5
    )

    assert outcome.ok is True
    assert outcome.sl_ok is True
    assert outcome.tp_ok is False
    assert trade.status == "OPEN"
