import os

# Los tests SIEMPRE corren con entorno limpio: las variables de entorno tienen
# prioridad sobre el .env real del usuario (que puede tener claves y live activado).
_TEST_ENV = {
    "MONITOR_ENABLED": "false",
    "LIVE_MODE_ENABLED": "false",
    "BROKER_ENABLED": "false",
    "AUTONOMOUS_TRADING_ENABLED": "false",
    "BINANCE_API_KEY": "",
    "BINANCE_API_SECRET": "",
    "BINANCE_TESTNET": "false",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "TELEGRAM_COMMANDS_ENABLED": "false",
    "KELLY_ENABLED": "false",
    "ML_FILTER_ENABLED": "false",
    "AI_ENABLED": "false",
    "DEBUG": "false",
}
for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value

from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from trading_bot.config.settings import get_settings
from trading_bot.db.base import Base
from trading_bot.db.models import Account, AlertLog, AuditLog, BacktestRun, PaperTrade, Signal  # noqa: F401
from trading_bot.db.session import get_db
from trading_bot.main import app
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector
from trading_bot.features.signals.strategies.trend_pullback_mvp import MarketContext
from trading_bot.schemas.risk import AccountRiskState

get_settings.cache_clear()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def sample_market_context() -> MarketContext:
    data = DataCollector.generate_sample_data(500)
    return MarketContext(
        symbol="BTC/USDT",
        df_4h=data["4h"],
        df_1h=data["1h"],
        df_15m=data["15m"],
    )


@pytest.fixture
def account_state() -> AccountRiskState:
    return AccountRiskState(balance_usdt=Decimal("10000"))
