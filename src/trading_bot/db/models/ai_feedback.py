from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.db.base import Base


class AIFeedback(Base):
    """Retroalimentación de análisis IA para few-shot learning."""

    __tablename__ = "ai_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(30))
    direction: Mapped[str] = mapped_column(String(10))
    setup_grade: Mapped[str] = mapped_column(String(5))
    ai_verdict: Mapped[str] = mapped_column(String(20))
    ai_summary: Mapped[str] = mapped_column(Text)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    user_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
