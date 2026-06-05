from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from trading_bot.config.settings import Settings
from trading_bot.core.enums import AlertType, SignalStatus, TradeDirection
from trading_bot.db.base import Base
from trading_bot.db.models import AlertLog, PaperTrade, Signal  # noqa: F401
from trading_bot.features.signals.monitor.service import SignalMonitorService


@pytest.fixture
async def monitor_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def monitor_settings() -> Settings:
    return Settings(
        monitor_enabled=True,
        watch_symbols="BTC/USDT",
        scan_interval_seconds=0,
        price_check_interval_seconds=0,
        entry_proximity_percent=1.0,
        signal_ttl_hours=4,
        dedup_signal_minutes=0,
        auto_paper_trade=True,
        monitor_use_live_data=False,
        telegram_bot_token="",
        telegram_chat_id="",
    )


@pytest.fixture
async def watching_signal(monitor_session) -> Signal:
    async with monitor_session() as session:
        signal = Signal(
            symbol="BTC/USDT",
            direction=TradeDirection.LONG.value,
            primary_timeframe="1h",
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit_1=Decimal("51000"),
            take_profit_2=Decimal("52000"),
            account_balance=Decimal("10000"),
            risk_percent=Decimal("0.5"),
            risk_usdt=Decimal("50"),
            position_size=Decimal("2500"),
            margin_required=Decimal("500"),
            recommended_leverage=3,
            setup_grade="A",
            should_trade=True,
            status=SignalStatus.WATCHING.value,
            expires_at=datetime.now(UTC) + timedelta(hours=4),
        )
        session.add(signal)
        await session.commit()
        await session.refresh(signal)
        return signal


def test_entry_hit_long() -> None:
    signal = MagicMock()
    signal.entry_price = Decimal("50000")
    signal.direction = TradeDirection.LONG.value
    assert SignalMonitorService._entry_hit(signal, Decimal("49900")) is True
    assert SignalMonitorService._entry_hit(signal, Decimal("50100")) is False


@pytest.mark.asyncio
async def test_watch_sends_entry_now_alert(monitor_session, monitor_settings, watching_signal) -> None:
    service = SignalMonitorService(monitor_session, monitor_settings)
    service.notifier.send_raw = AsyncMock(return_value=True)
    service.price_feed.get_price = MagicMock(return_value=Decimal("49900"))

    alerts = await service._watch_active_signals()
    assert alerts >= 1

    async with monitor_session() as session:
        from sqlalchemy import select

        result = await session.execute(select(Signal).where(Signal.id == watching_signal.id))
        updated = result.scalar_one()
        assert updated.status == SignalStatus.ACTIVE.value

        alerts_db = await session.execute(
            select(AlertLog).where(AlertLog.signal_id == watching_signal.id)
        )
        types = {a.alert_type for a in alerts_db.scalars().all()}
        assert AlertType.ENTRY_NOW.value in types


@pytest.mark.asyncio
async def test_entry_approaching_alert(monitor_session, monitor_settings, watching_signal) -> None:
    service = SignalMonitorService(monitor_session, monitor_settings)
    service.notifier.send_raw = AsyncMock(return_value=True)
    service.price_feed.get_price = MagicMock(return_value=Decimal("50200"))

    alerts = await service._watch_active_signals()
    assert alerts >= 1

    async with monitor_session() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(AlertLog).where(
                AlertLog.signal_id == watching_signal.id,
                AlertLog.alert_type == AlertType.ENTRY_APPROACHING.value,
            )
        )
        assert result.scalar_one_or_none() is not None


@pytest.mark.asyncio
async def test_scan_creates_signal_with_mock(monitor_session, monitor_settings) -> None:
    service = SignalMonitorService(monitor_session, monitor_settings)
    service.notifier.send_raw = AsyncMock(return_value=True)
    service.price_feed.get_market_data = MagicMock(
        return_value=__import__(
            "trading_bot.infrastructure.market_data.ccxt_client", fromlist=["DataCollector"]
        ).DataCollector.generate_trending_bullish_data()
    )

    with patch.object(service.generator, "generate") as mock_gen:
        from trading_bot.core.enums import SetupGrade
        from trading_bot.schemas.signal import SignalCreate

        mock_gen.return_value = SignalCreate(
            symbol="BTC/USDT",
            direction=TradeDirection.LONG,
            primary_timeframe="1h",
            entry_price=Decimal("50000"),
            stop_loss=Decimal("49000"),
            take_profit_1=Decimal("51000"),
            take_profit_2=Decimal("52000"),
            risk_reward_ratio=Decimal("2"),
            account_balance=Decimal("10000"),
            risk_percent=Decimal("1"),
            risk_usdt=Decimal("100"),
            recommended_capital_usdt=Decimal("500"),
            recommended_leverage=3,
            max_loss_usdt=Decimal("100"),
            estimated_gain_tp1_usdt=Decimal("100"),
            estimated_gain_tp2_usdt=Decimal("200"),
            position_size=Decimal("2500"),
            margin_required=Decimal("500"),
            setup_grade=SetupGrade.A,
            confidence_score=Decimal("85"),
            technical_explanation="Test bullish",
            invalidation_conditions="SL break",
            should_trade=True,
        )
        count = await service._scan_symbols()
        assert count >= 1
