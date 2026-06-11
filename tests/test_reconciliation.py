"""Reconciliación DB ↔ exchange: cierres con PnL real, SL repuestos, piso de equity."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.db.init_db import ensure_bot_state
from trading_bot.db.models.account import Account
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.reconciliation.service import ReconciliationService

from tests.test_protection import FakeNotifier


def _settings(**overrides) -> Settings:
    data = get_settings().model_dump()
    data.update(
        binance_api_key="k",
        binance_api_secret="s",
        broker_enabled=True,
        exchange_retry_max_attempts=1,
        sl_placement_max_retries=1,
        sl_placement_backoff_base_seconds=0.001,
        initial_equity_usdt=500.0,
        max_total_loss_usdt=50.0,
        **overrides,
    )
    return Settings(**data)


def _mock_broker(settings: Settings) -> BinanceBroker:
    broker = BinanceBroker(settings)
    exchange = MagicMock()
    exchange.fetch_positions.return_value = []
    exchange.fetch_open_orders.return_value = []
    exchange.fetch_my_trades.return_value = []
    exchange.fetch_balance.return_value = {"info": {"totalMarginBalance": "500"}, "USDT": {"total": 500}}
    exchange.price_to_precision.side_effect = lambda _s, p: str(p)
    exchange.create_order.return_value = {"id": "R-1", "status": "open"}
    broker._collector._exchange = exchange
    return broker


async def _make_broker_trade(session: AsyncSession, **overrides) -> tuple[Account, UserTrade]:
    account = Account(name="recon", balance_usdt=Decimal("500"))
    session.add(account)
    await session.flush()
    fields = dict(
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
        notes="auto-entry | Binance E-1",
    )
    fields.update(overrides)
    trade = UserTrade(**fields)
    session.add(trade)
    await session.commit()
    return account, trade


@pytest.mark.asyncio
async def test_caso_a_trade_cerrado_en_exchange_con_pnl_real(db_session: AsyncSession) -> None:
    settings = _settings()
    broker = _mock_broker(settings)
    account, trade = await _make_broker_trade(db_session)

    # El exchange ya no tiene la posición; los fills traen el PnL real (cerró por SL)
    broker.exchange.fetch_my_trades.return_value = [
        {
            "price": 49000.0,
            "info": {"realizedPnl": "-2.50", "clientOrderId": f"tbot-{trade.id}-sl"},
        }
    ]
    service = ReconciliationService(db_session, settings, broker=broker, notifier=FakeNotifier())
    report = await service.run()

    assert trade.id in report.closed_trades
    assert trade.status == "CLOSED"
    assert trade.close_reason == "STOP_LOSS"
    assert trade.pnl_usdt == Decimal("-2.50")
    assert trade.exit_price == Decimal("49000.0")
    assert account.balance_usdt == Decimal("497.50")
    assert account.consecutive_losses == 1
    broker.exchange.cancel_all_orders.assert_called()


@pytest.mark.asyncio
async def test_caso_b_posicion_desconocida_solo_alerta(db_session: AsyncSession) -> None:
    settings = _settings(adopt_unknown_positions=False)
    broker = _mock_broker(settings)
    notifier = FakeNotifier()
    broker.exchange.fetch_positions.return_value = [
        {"symbol": "ETH/USDT:USDT", "side": "short", "contracts": "1.5"}
    ]
    service = ReconciliationService(db_session, settings, broker=broker, notifier=notifier)
    report = await service.run()

    assert report.alerts == 1
    assert report.fixed == 0  # sin flatten con flag en false
    assert any("sin trade en DB" in str(a) for a in notifier.alerts)


@pytest.mark.asyncio
async def test_caso_c_sl_ausente_se_repone(db_session: AsyncSession) -> None:
    settings = _settings()
    broker = _mock_broker(settings)
    _, trade = await _make_broker_trade(db_session)

    broker.exchange.fetch_positions.return_value = [
        {"symbol": "BTC/USDT:USDT", "side": "long", "contracts": "0.002"}
    ]
    broker.exchange.fetch_open_orders.return_value = []  # ¡sin SL activa!
    broker.exchange.fetch_order.side_effect = __import__("ccxt").OrderNotFound("no")

    service = ReconciliationService(db_session, settings, broker=broker, notifier=FakeNotifier())
    report = await service.run()

    assert trade.id in report.sl_restored
    sl_calls = [
        c for c in broker.exchange.create_order.call_args_list if c.args[1] == "stop_market"
    ]
    assert sl_calls, "debió reponer el SL"
    # clientOrderId original reutilizado
    assert sl_calls[0].args[5]["clientOrderId"] == f"tbot-{trade.id}-sl"


@pytest.mark.asyncio
async def test_caso_c_sl_condicional_del_api_nuevo_es_reconocida(db_session: AsyncSession) -> None:
    """Regresión del bug SL_MISSING_ON_RECONCILE: las SL condicionales del API
    nuevo reportan type unificado 'market' (el real va en info.orderType) y la
    reconciliación las aplanaba creyéndolas ausentes."""
    settings = _settings()
    broker = _mock_broker(settings)
    _, trade = await _make_broker_trade(db_session)

    broker.exchange.fetch_positions.return_value = [
        {"symbol": "BTC/USDT:USDT", "side": "long", "contracts": "0.002"}
    ]
    broker.exchange.fetch_open_orders.return_value = [
        {
            "symbol": "BTC/USDT:USDT",
            "type": "market",  # ¡así reporta CCXT las algo orders!
            "status": "open",
            "stopPrice": 49000.0,
            "clientOrderId": f"tbot-{trade.id}-sl",
            "info": {"orderType": "STOP_MARKET", "algoType": "CONDITIONAL", "algoStatus": "NEW"},
        }
    ]

    service = ReconciliationService(db_session, settings, broker=broker, notifier=FakeNotifier())
    report = await service.run()

    assert trade.status == "OPEN"  # protegida: NI se aplana NI se toca
    assert trade.id not in report.sl_restored
    sl_calls = [
        c for c in broker.exchange.create_order.call_args_list if c.args[1] == "stop_market"
    ]
    assert not sl_calls  # no intentó reponer un SL que ya existe


@pytest.mark.asyncio
async def test_caso_e_ordenes_huerfanas_canceladas(db_session: AsyncSession) -> None:
    settings = _settings()
    broker = _mock_broker(settings)
    broker.exchange.fetch_open_orders.return_value = [
        {"symbol": "SOL/USDT:USDT", "type": "stop_market"}
    ]
    service = ReconciliationService(db_session, settings, broker=broker, notifier=FakeNotifier())
    report = await service.run()

    assert "SOL/USDT:USDT" in report.orphan_orders_cancelled


@pytest.mark.asyncio
async def test_piso_de_equity_dispara_kill_switch_una_vez(db_session: AsyncSession) -> None:
    """Equity 449 <= piso 450 (500-50) → kill-switch; segunda pasada no repite."""
    settings = _settings()
    broker = _mock_broker(settings)
    broker.exchange.fetch_balance.return_value = {
        "info": {"totalMarginBalance": "449"},
        "USDT": {"total": 449},
    }
    notifier = FakeNotifier()
    service = ReconciliationService(db_session, settings, broker=broker, notifier=notifier)

    report1 = await service.run()
    assert report1.kill_switch_triggered is True
    state = await ensure_bot_state(db_session)
    assert state.kill_switch_engaged is True
    assert state.equity_floor_breached_at is not None

    report2 = await service.run()
    assert report2.kill_switch_triggered is False  # no repite el flatten
