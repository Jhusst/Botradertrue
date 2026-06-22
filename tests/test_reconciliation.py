"""Reconciliación DB ↔ exchange: cierres con PnL real, SL repuestos, piso de equity."""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.db.init_db import ensure_bot_state
from trading_bot.db.models.account import Account
from trading_bot.db.models.broker_order import BrokerOrder
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.reconciliation import service as recon_service
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


@pytest.mark.asyncio
async def test_no_cierra_sin_fill_de_cierre(db_session: AsyncSession) -> None:
    """Regresión DOGE: posición ausente pero SIN fill de cierre = parpadeo de
    fetch_positions → el trade debe quedar OPEN, no inventar un cierre."""
    settings = _settings()
    broker = _mock_broker(settings)
    _, trade = await _make_broker_trade(db_session)
    broker.exchange.fetch_positions.return_value = []   # posición no visible...
    broker.exchange.fetch_my_trades.return_value = []   # ...pero NO hubo cierre real

    service = ReconciliationService(db_session, settings, broker=broker, notifier=FakeNotifier())
    report = await service.run()

    assert trade.status == "OPEN"          # NO se cierra a ciegas
    assert trade.id not in report.closed_trades


@pytest.mark.asyncio
async def test_readopta_posicion_cerrada_por_error(db_session: AsyncSession) -> None:
    """Una posición viva en Binance cuyo trade quedó CLOSED por error (sin PnL)
    se re-adopta a OPEN en vez de alertar como desconocida."""
    settings = _settings()
    broker = _mock_broker(settings)
    account, trade = await _make_broker_trade(
        db_session, symbol="DOGE/USDT", direction="SHORT", status="CLOSED",
        close_reason="EXCHANGE_CLOSED", entry_price=Decimal("0.084"), stop_loss=Decimal("0.085"),
    )
    db_session.add(BrokerOrder(
        user_trade_id=trade.id, client_order_id=f"tbot-{trade.id}-e",
        kind=BrokerOrder.KIND_ENTRY, symbol="DOGE/USDT", side="sell",
        order_type="market", status=BrokerOrder.STATUS_ACKED, exchange_order_id="X1",
    ))
    await db_session.commit()

    broker.exchange.fetch_positions.return_value = [
        {"symbol": "DOGE/USDT:USDT", "side": "short", "contracts": "8774"}
    ]
    notifier = FakeNotifier()
    service = ReconciliationService(db_session, settings, broker=broker, notifier=notifier)
    report = await service.run()

    await db_session.refresh(trade)
    assert trade.status == "OPEN"                      # re-adoptado
    assert report.alerts == 0                          # NO se contó como desconocida
    assert "re-sincronizada" in str(notifier.alerts)


@pytest.mark.asyncio
async def test_alerta_de_desconocida_tiene_throttle(db_session: AsyncSession) -> None:
    """Una posición genuinamente desconocida alerta UNA vez, no en cada ciclo."""
    recon_service._last_unknown_alert.clear()
    settings = _settings(adopt_unknown_positions=False)
    broker = _mock_broker(settings)
    broker.exchange.fetch_positions.return_value = [
        {"symbol": "XRP/USDT:USDT", "side": "long", "contracts": "100"}
    ]
    notifier = FakeNotifier()

    for _ in range(3):  # tres ciclos seguidos
        service = ReconciliationService(db_session, settings, broker=broker, notifier=notifier)
        await service.run()

    mismatches = [a for a in notifier.alerts if "sin trade en DB" in str(a)]
    assert len(mismatches) == 1  # solo la primera, el resto silenciado por throttle


@pytest.mark.asyncio
async def test_readopta_trade_cerrado_por_signal_expired_revierte_pnl(db_session: AsyncSession) -> None:
    """Trade con posición viva en Binance pero CLOSED por SIGNAL_EXPIRED con PnL
    estimado aplicado: se re-adopta y se revierte el PnL inventado a la cuenta."""
    recon_service._last_unknown_alert.clear()
    settings = _settings()
    broker = _mock_broker(settings)
    account, trade = await _make_broker_trade(
        db_session, symbol="DOGE/USDT", direction="SHORT", status="CLOSED",
        close_reason="SIGNAL_EXPIRED", entry_price=Decimal("0.084"), stop_loss=Decimal("0.085"),
        exit_price=Decimal("0.0845"), pnl_usdt=Decimal("-3.00"),
    )
    account.balance_usdt = Decimal("497")  # el cierre por expiración ya restó 3
    db_session.add(BrokerOrder(
        user_trade_id=trade.id, client_order_id=f"tbot-{trade.id}-e",
        kind=BrokerOrder.KIND_ENTRY, symbol="DOGE/USDT", side="sell",
        order_type="market", status=BrokerOrder.STATUS_ACKED, exchange_order_id="X1",
    ))
    await db_session.commit()

    broker.exchange.fetch_positions.return_value = [
        {"symbol": "DOGE/USDT:USDT", "side": "short", "contracts": "8774"}
    ]
    service = ReconciliationService(db_session, settings, broker=broker, notifier=FakeNotifier())
    await service.run()

    await db_session.refresh(trade)
    await db_session.refresh(account)
    assert trade.status == "OPEN"
    assert trade.pnl_usdt is None
    assert account.balance_usdt == Decimal("500")  # PnL estimado revertido


@pytest.mark.asyncio
async def test_no_readopta_cierre_real_por_stop_loss(db_session: AsyncSession) -> None:
    """Un trade cerrado por STOP_LOSS real NO se re-adopta aunque haya una
    posición del mismo símbolo/dirección (sería una posición nueva distinta)."""
    recon_service._last_unknown_alert.clear()
    settings = _settings(adopt_unknown_positions=False)
    broker = _mock_broker(settings)
    _, trade = await _make_broker_trade(
        db_session, symbol="DOGE/USDT", direction="SHORT", status="CLOSED",
        close_reason="STOP_LOSS", pnl_usdt=Decimal("-2.5"),
    )
    db_session.add(BrokerOrder(
        user_trade_id=trade.id, client_order_id=f"tbot-{trade.id}-e",
        kind=BrokerOrder.KIND_ENTRY, symbol="DOGE/USDT", side="sell",
        order_type="market", status=BrokerOrder.STATUS_ACKED, exchange_order_id="X1",
    ))
    await db_session.commit()

    broker.exchange.fetch_positions.return_value = [
        {"symbol": "DOGE/USDT:USDT", "side": "short", "contracts": "100"}
    ]
    notifier = FakeNotifier()
    service = ReconciliationService(db_session, settings, broker=broker, notifier=notifier)
    report = await service.run()

    await db_session.refresh(trade)
    assert trade.status == "CLOSED"      # NO se re-adopta
    assert report.alerts == 1            # se trata como desconocida
