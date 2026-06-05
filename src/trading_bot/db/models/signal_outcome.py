from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trading_bot.db.base import Base


class SignalOutcome(Base):
    """Resultado hipotético o real de una señal (para medir efectividad sin ejecutar)."""

    __tablename__ = "signal_outcomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), unique=True, index=True)

    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entry_touched: Mapped[bool] = mapped_column(Boolean, default=False)

    outcome: Mapped[str] = mapped_column(String(30), default="PENDING")
    outcome_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    min_price_seen: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    max_price_seen: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    symbol: Mapped[str] = mapped_column(String(30))
    direction: Mapped[str] = mapped_column(String(20))
    setup_grade: Mapped[str] = mapped_column(String(5))

    tracking_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    signal = relationship("Signal", backref="outcome")
