from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from trading_bot.db.base import Base

BOT_STATE_ID = 1


class BotState(Base):
    """Estado de seguridad persistente (fila única, id=1).

    Sobrevive reinicios: pausa de entradas, kill-switch y heartbeat
    del monitor viven aquí, no en memoria.
    """

    __tablename__ = "bot_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=BOT_STATE_ID)
    entries_paused: Mapped[bool] = mapped_column(Boolean, default=False)
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    kill_switch_engaged: Mapped[bool] = mapped_column(Boolean, default=False)
    kill_switch_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    equity_floor_breached_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_update_offset: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
