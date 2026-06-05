from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trading_bot.db.base import Base


class UserTrade(Base):
    """Trade real registrado manualmente por el usuario (ej. en Bitunix)."""

    __tablename__ = "user_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True)

    symbol: Mapped[str] = mapped_column(String(30))
    direction: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")

    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    take_profit_1: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    take_profit_2: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    margin_used: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    leverage: Mapped[int] = mapped_column(Integer, default=1)
    risk_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))

    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    pnl_usdt: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account", backref="user_trades")
    signal = relationship("Signal", backref="user_trades")
