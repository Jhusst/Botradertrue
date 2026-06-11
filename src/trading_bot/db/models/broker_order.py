from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trading_bot.db.base import Base


class BrokerOrder(Base):
    """Intent persistido de cada orden enviada al broker.

    Se escribe ANTES de tocar la red: el client_order_id determinístico
    (tbot-{trade_id}-{kind}) hace imposible duplicar órdenes en reintentos
    y permite reconciliar contra el exchange tras un crash.
    """

    __tablename__ = "broker_orders"

    # Estados del ciclo de vida del intent
    STATUS_INTENT = "INTENT"      # persistido, aún no enviado
    STATUS_SENT = "SENT"          # enviado, sin respuesta confirmada
    STATUS_ACKED = "ACKED"        # el exchange lo aceptó
    STATUS_FILLED = "FILLED"
    STATUS_CANCELED = "CANCELED"
    STATUS_REJECTED = "REJECTED"  # confirmado que nunca llegó / fue rechazado
    STATUS_UNKNOWN = "UNKNOWN"

    KIND_ENTRY = "ENTRY"
    KIND_SL = "SL"
    KIND_TP = "TP"
    KIND_FLATTEN = "FLATTEN"
    KIND_MANUAL_CLOSE = "MANUAL_CLOSE"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_trade_id: Mapped[int | None] = mapped_column(ForeignKey("user_trades.id"), nullable=True)

    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    symbol: Mapped[str] = mapped_column(String(40))
    side: Mapped[str] = mapped_column(String(10))
    order_type: Mapped[str] = mapped_column(String(30))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(28, 12), nullable=True)
    trigger_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    leverage: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(String(20), default=STATUS_INTENT)
    exchange_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user_trade = relationship("UserTrade", backref="broker_orders")
