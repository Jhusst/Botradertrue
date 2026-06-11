from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.exceptions import LiveModeBlockedError
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.broker.engine import ExecutionEngine


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **kwargs) -> Settings:
    base = get_settings()
    data = base.model_dump()
    data.update(kwargs)
    custom = Settings(**data)
    monkeypatch.setattr(
        "trading_bot.features.broker.binance_broker.get_settings",
        lambda: custom,
    )
    monkeypatch.setattr(
        "trading_bot.features.broker.engine.get_settings",
        lambda: custom,
    )
    return custom


def test_broker_not_configured_without_keys() -> None:
    broker = BinanceBroker()
    assert broker.is_configured() is False
    snap = broker.fetch_account()
    assert snap.connected is False
    assert "no configuradas" in snap.message.lower()


def test_can_execute_requires_all_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, broker_enabled=False, binance_api_key="")
    broker = BinanceBroker()
    can, reason = broker.can_execute()
    assert can is False
    assert "BROKER_ENABLED" in reason


def test_execute_raises_when_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, live_mode_enabled=False, broker_enabled=True, binance_api_key="k")
    engine = ExecutionEngine()
    with pytest.raises(LiveModeBlockedError):
        engine.execute(
            symbol="BTC/USDT",
            direction="LONG",
            entry_price=Decimal("50000"),
            position_size_usdt=Decimal("10"),
            leverage=5,
        )


def test_open_position_returns_error_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, broker_enabled=False)
    broker = BinanceBroker()
    result = broker.open_position(
        symbol="BTC/USDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        position_size_usdt=Decimal("10"),
        leverage=5,
    )
    assert result.ok is False


def test_parse_algo_order_normaliza_condicionales() -> None:
    raw = {
        "algoId": "1000000102924178",
        "clientAlgoId": "tbot-9-sl",
        "algoStatus": "NEW",
        "orderType": "STOP_MARKET",
        "triggerPrice": "5.5",
        "symbol": "AVAXUSDT",
    }
    parsed = BinanceBroker._parse_algo_order(raw)
    assert parsed["status"] == "open"
    assert parsed["clientOrderId"] == "tbot-9-sl"
    assert parsed["type"] == "stop_market"
    assert parsed["stopPrice"] == "5.5"

    triggered = BinanceBroker._parse_algo_order({**raw, "algoStatus": "TRIGGERED"})
    assert triggered["status"] == "closed"
    cancelled = BinanceBroker._parse_algo_order({**raw, "algoStatus": "CANCELLED"})
    assert cancelled["status"] == "canceled"
    assert BinanceBroker._parse_algo_order([]) is None
    assert BinanceBroker._parse_algo_order(None) is None
    assert BinanceBroker._parse_algo_order({"sin_algo_id": 1}) is None


@patch.object(BinanceBroker, "can_execute", return_value=(True, "ok"))
@patch.object(BinanceBroker, "resolve_futures_symbol", return_value="BTC/USDT:USDT")
def test_open_position_success_mock(_resolve, _can, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        broker_enabled=True,
        auto_execute_on_enter=True,
        live_mode_enabled=True,
        binance_api_key="key",
        binance_api_secret="secret",
    )
    broker = BinanceBroker()
    mock_exchange = MagicMock()
    mock_exchange.amount_to_precision.return_value = "0.001"
    mock_exchange.create_order.return_value = {"id": "12345"}
    mock_exchange.price_to_precision.side_effect = lambda _s, p: str(p)
    broker._collector._exchange = mock_exchange

    result = broker.open_position(
        symbol="BTC/USDT",
        direction="LONG",
        entry_price=Decimal("50000"),
        position_size_usdt=Decimal("50"),
        leverage=10,
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("52000"),
    )
    assert result.ok is True
    assert result.order_id == "12345"
