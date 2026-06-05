from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.db.base import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="default")
    profile_type: Mapped[str] = mapped_column(String(20), default="conservative", index=True)
    balance_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("60"))
    initial_balance_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("60"))
    risk_setup_a: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0.25"))
    risk_setup_b: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0.15"))
    max_leverage: Mapped[int] = mapped_column(default=3)
    min_setup_grade: Mapped[str] = mapped_column(String(5), default="A")
    mode: Mapped[str] = mapped_column(String(20), default="PAPER")
    live_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_pnl_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    weekly_pnl_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    consecutive_losses: Mapped[int] = mapped_column(default=0)
    max_drawdown_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
