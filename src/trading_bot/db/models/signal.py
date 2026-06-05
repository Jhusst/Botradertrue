from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trading_bot.db.base import Base


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=True)

    symbol: Mapped[str] = mapped_column(String(30), index=True)
    direction: Mapped[str] = mapped_column(String(20))
    primary_timeframe: Mapped[str] = mapped_column(String(10))

    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    stop_loss: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    take_profit_1: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    take_profit_2: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    risk_reward_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)

    account_balance: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    risk_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    risk_usdt: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    recommended_capital_usdt: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    recommended_leverage: Mapped[int | None] = mapped_column(Integer, nullable=True)

    max_loss_usdt: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    estimated_gain_tp1_usdt: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    estimated_gain_tp2_usdt: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    position_size: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    margin_required: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    stop_distance_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tp1_distance_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tp2_distance_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    setup_grade: Mapped[str] = mapped_column(String(5))
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    technical_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    invalidation_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    should_trade: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    strategy_name: Mapped[str] = mapped_column(String(100), default="TrendPullbackMVP")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    account = relationship("Account", backref="signals")
