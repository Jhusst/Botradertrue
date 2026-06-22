from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from trading_bot.config.settings import Settings, get_settings
from trading_bot.features.autonomous.service import AutonomousTraderService, AI_VERDICT_RANK
from trading_bot.features.broker.binance_broker import BrokerOrderResult


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **kwargs) -> Settings:
    base = get_settings()
    data = base.model_dump()
    data.update(kwargs)
    custom = Settings(**data)
    monkeypatch.setattr(
        "trading_bot.features.autonomous.service.get_settings",
        lambda: custom,
    )
    return custom


def test_ai_verdict_rank() -> None:
    assert AI_VERDICT_RANK["CONFIRM"] > AI_VERDICT_RANK["NEUTRAL"]
    assert AI_VERDICT_RANK["DISAGREE"] < AI_VERDICT_RANK["CAUTION"]


def test_ai_allows_confirm_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, ai_gate_auto_trade=True, ai_enabled=True, ai_auto_min_verdict="CONFIRM")
    from sqlalchemy.ext.asyncio import AsyncSession

    class FakeSession:
        pass

    svc = AutonomousTraderService(FakeSession())  # type: ignore[arg-type]
    assert svc._ai_allows("CONFIRM") is True
    assert svc._ai_allows("NEUTRAL") is False
    assert svc._ai_allows("DISAGREE") is False


@pytest.mark.asyncio
async def test_process_entry_disabled(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, autonomous_trading_enabled=False)
    from trading_bot.db.models.signal import Signal
    from trading_bot.db.seed_profiles import ensure_profiles
    from trading_bot.core.enums import SignalStatus

    await ensure_profiles(db_session)
    signal = Signal(
        account_id=1,
        symbol="BTC/USDT",
        direction="LONG",
        primary_timeframe="1h",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        account_balance=Decimal("2"),
        risk_percent=Decimal("0.25"),
        setup_grade="A",
        should_trade=True,
        status=SignalStatus.WATCHING.value,
    )
    db_session.add(signal)
    await db_session.flush()

    svc = AutonomousTraderService(db_session)
    result = await svc.process_entry(signal, Decimal("49900"))
    assert result.executed is False


@pytest.mark.asyncio
async def test_process_entry_ai_blocks(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(
        monkeypatch,
        autonomous_trading_enabled=True,
        ai_gate_auto_trade=True,
        ai_enabled=True,
        ai_auto_min_verdict="CONFIRM",
        min_balance_for_autonomous=1.0,
    )
    from trading_bot.db.models.signal import Signal
    from trading_bot.db.seed_profiles import ensure_profiles
    from trading_bot.core.enums import SignalStatus
    from trading_bot.features.ai.analyzer import AIAnalysisResult

    await ensure_profiles(db_session)
    signal = Signal(
        account_id=1,
        symbol="BTC/USDT",
        direction="LONG",
        primary_timeframe="1h",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("51000"),
        take_profit_2=Decimal("52000"),
        setup_grade="A",
        account_balance=Decimal("2"),
        risk_percent=Decimal("0.25"),
        technical_explanation="test",
        should_trade=True,
        status=SignalStatus.WATCHING.value,
        margin_required=Decimal("1"),
        position_size=Decimal("10"),
        recommended_leverage=5,
        risk_usdt=Decimal("0.05"),
    )
    db_session.add(signal)
    await db_session.flush()

    mock_analysis = AIAnalysisResult(
        verdict="DISAGREE",
        confidence_delta=Decimal("-5"),
        summary="Riesgo alto",
        risks=[],
        invalidation_hint="",
        raw_response="",
        model_used="test",
        available=True,
    )

    with patch.object(
        AutonomousTraderService,
        "_send_autonomous_alert",
        new_callable=AsyncMock,
    ), patch.object(
        AutonomousTraderService,
        "_notify_blocked",
        new_callable=AsyncMock,
    ), patch(
        "trading_bot.features.autonomous.service.AIChartAnalyzer.analyze_setup",
        new_callable=AsyncMock,
        return_value=mock_analysis,
    ):
        svc = AutonomousTraderService(db_session)
        result = await svc.process_entry(signal, Decimal("49900"))

    assert result.executed is False
    assert result.ai_verdict == "DISAGREE"


@pytest.mark.asyncio
async def test_signal_expired_no_cierra_trade_de_broker(db_session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Una señal que caduca NO cierra un trade con posición REAL en Binance:
    ese trade vive hasta que su SL/TP se ejecute (lo cierra la reconciliación)."""
    from decimal import Decimal

    from trading_bot.db.models.account import Account
    from trading_bot.db.models.signal import Signal
    from trading_bot.db.models.user_trade import UserTrade

    _patch_settings(monkeypatch, broker_enabled=True)

    account = Account(name="x", balance_usdt=Decimal("500"))
    db_session.add(account)
    await db_session.flush()
    signal = Signal(
        account_id=account.id, symbol="DOGE/USDT", direction="SHORT", primary_timeframe="1h",
        account_balance=Decimal("500"), risk_percent=Decimal("0.5"), setup_grade="A",
        entry_price=Decimal("0.084"), stop_loss=Decimal("0.085"), should_trade=True,
    )
    db_session.add(signal)
    await db_session.flush()

    broker_trade = UserTrade(
        account_id=account.id, signal_id=signal.id, symbol="DOGE/USDT", direction="SHORT",
        status="OPEN", entry_price=Decimal("0.084"), stop_loss=Decimal("0.085"),
        margin_used=Decimal("10"), leverage=5, risk_usdt=Decimal("2.5"),
        notes="auto-entry @ 0.084 | Binance 1007791657",
    )
    paper_trade = UserTrade(
        account_id=account.id, signal_id=signal.id, symbol="DOGE/USDT", direction="SHORT",
        status="OPEN", entry_price=Decimal("0.084"), stop_loss=Decimal("0.085"),
        margin_used=Decimal("10"), leverage=5, risk_usdt=Decimal("2.5"),
        notes="manual|lev=5x",
    )
    db_session.add_all([broker_trade, paper_trade])
    await db_session.commit()

    svc = AutonomousTraderService(db_session)  # Telegram sin configurar en tests
    await svc.close_trades_on_signal_expired(signal, Decimal("0.084"))

    await db_session.refresh(broker_trade)
    await db_session.refresh(paper_trade)
    assert broker_trade.status == "OPEN"     # protegido: lo gestiona el exchange
    assert paper_trade.status == "CLOSED"    # paper sí se cierra al expirar
