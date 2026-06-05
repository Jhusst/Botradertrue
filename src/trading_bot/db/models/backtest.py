from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.db.base import Base


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(100))
    symbol: Mapped[str] = mapped_column(String(30))
    timeframe: Mapped[str] = mapped_column(String(10))
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    initial_balance: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    final_balance: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    total_trades: Mapped[int] = mapped_column(Integer)
    winning_trades: Mapped[int] = mapped_column(Integer)
    losing_trades: Mapped[int] = mapped_column(Integer)

    win_rate: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    profit_factor: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    max_drawdown_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    sharpe_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    expectancy: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    avg_win_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    avg_loss_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    max_loss_streak: Mapped[int] = mapped_column(Integer)
    net_pnl_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8))

    commission_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    slippage_rate: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    parameters: Mapped[str | None] = mapped_column(Text, nullable=True)
    passed_validation: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
