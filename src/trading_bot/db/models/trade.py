from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trading_bot.db.base import Base


class PaperTrade(Base):
    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))

    symbol: Mapped[str] = mapped_column(String(30))
    direction: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")

    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    take_profit_1: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    take_profit_2: Mapped[Decimal] = mapped_column(Numeric(18, 8))

    position_size: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    leverage: Mapped[int] = mapped_column(Integer)
    margin_used: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    risk_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8))

    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    pnl_usdt: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    pnl_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    signal = relationship("Signal", backref="paper_trades")
    account = relationship("Account", backref="paper_trades")
