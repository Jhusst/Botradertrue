from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from trading_bot.db.base import Base
from trading_bot.db.models import (  # noqa: F401
    Account,
    AIFeedback,
    AlertLog,
    AuditLog,
    BacktestRun,
    BotState,
    BrokerOrder,
    PaperTrade,
    Signal,
    SignalOutcome,
    UserTrade,
)
from trading_bot.db.models.bot_state import BOT_STATE_ID
from trading_bot.db.seed_profiles import ensure_profiles


async def ensure_bot_state(session: AsyncSession) -> BotState:
    """Garantiza la fila única de estado de seguridad (id=1)."""
    result = await session.execute(select(BotState).where(BotState.id == BOT_STATE_ID))
    state = result.scalar_one_or_none()
    if state is None:
        state = BotState(id=BOT_STATE_ID)
        session.add(state)
        await session.flush()
    return state

SIGNALS_EXTRA_COLUMNS = {
    "last_price": "NUMERIC(18, 8)",
    "expires_at": "DATETIME",
    "updated_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
    "ml_probability": "NUMERIC(8, 4)",
    "ml_model_version": "VARCHAR(50)",
}


async def _migrate_sqlite_columns(engine: AsyncEngine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return

    async with engine.begin() as conn:
        def _get_columns(sync_conn):
            inspector = inspect(sync_conn)
            if not inspector.has_table("signals"):
                return set()
            return {col["name"] for col in inspector.get_columns("signals")}

        existing = await conn.run_sync(_get_columns)
        for name, col_type in SIGNALS_EXTRA_COLUMNS.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE signals ADD COLUMN {name} {col_type}"))


ACCOUNTS_EXTRA_COLUMNS = {
    "profile_type": "VARCHAR(20) DEFAULT 'conservative'",
    "risk_setup_a": "NUMERIC(8, 4) DEFAULT 0.25",
    "risk_setup_b": "NUMERIC(8, 4) DEFAULT 0.15",
    "max_leverage": "INTEGER DEFAULT 3",
    "min_setup_grade": "VARCHAR(5) DEFAULT 'A'",
}


async def _migrate_accounts_columns(engine: AsyncEngine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    async with engine.begin() as conn:
        def _get_columns(sync_conn):
            inspector = inspect(sync_conn)
            if not inspector.has_table("accounts"):
                return set()
            return {col["name"] for col in inspector.get_columns("accounts")}

        existing = await conn.run_sync(_get_columns)
        for name, col_type in ACCOUNTS_EXTRA_COLUMNS.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE accounts ADD COLUMN {name} {col_type}"))


SIGNAL_OUTCOMES_EXTRA_COLUMNS = {
    "min_price_seen": "NUMERIC(18, 8)",
    "max_price_seen": "NUMERIC(18, 8)",
}


async def _migrate_signal_outcomes_columns(engine: AsyncEngine) -> None:
    if not str(engine.url).startswith("sqlite"):
        return
    async with engine.begin() as conn:
        def _get_columns(sync_conn):
            inspector = inspect(sync_conn)
            if not inspector.has_table("signal_outcomes"):
                return set()
            return {col["name"] for col in inspector.get_columns("signal_outcomes")}

        existing = await conn.run_sync(_get_columns)
        for name, col_type in SIGNAL_OUTCOMES_EXTRA_COLUMNS.items():
            if name not in existing:
                await conn.execute(text(f"ALTER TABLE signal_outcomes ADD COLUMN {name} {col_type}"))


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _migrate_sqlite_columns(engine)
    await _migrate_accounts_columns(engine)
    await _migrate_signal_outcomes_columns(engine)
    from trading_bot.db.session import async_session_factory

    async with async_session_factory() as session:
        await ensure_profiles(session)
        await ensure_bot_state(session)
        await session.commit()
