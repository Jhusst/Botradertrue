from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from trading_bot.config.settings import Settings, get_settings
from trading_bot.modules.autonomous_trader.service import AutonomousTraderService, AI_VERDICT_RANK
from trading_bot.modules.execution_engine.binance_broker import BrokerOrderResult


def _patch_settings(monkeypatch: pytest.MonkeyPatch, **kwargs) -> Settings:
    base = get_settings()
    data = base.model_dump()
    data.update(kwargs)
    custom = Settings(**data)
    monkeypatch.setattr(
        "trading_bot.modules.autonomous_trader.service.get_settings",
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
    from trading_bot.modules.ai_chart_analyzer.analyzer import AIAnalysisResult

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
        "trading_bot.modules.autonomous_trader.service.AIChartAnalyzer.analyze_setup",
        new_callable=AsyncMock,
        return_value=mock_analysis,
    ):
        svc = AutonomousTraderService(db_session)
        result = await svc.process_entry(signal, Decimal("49900"))

    assert result.executed is False
    assert result.ai_verdict == "DISAGREE"
