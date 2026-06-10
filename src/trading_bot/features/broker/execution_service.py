"""Orquestador de ejecución con idempotencia y protección garantizada.

Invariantes que este servicio defiende:
1. Ningún create_order sin BrokerOrder(INTENT) commiteado antes en DB.
2. clientOrderId determinístico (tbot-{trade_id}-{kind}) → reintentos sin duplicar.
3. Una posición nunca queda sin stop-loss: si el SL falla tras los retries,
   la posición se cierra a mercado (flatten) inmediatamente.
4. Si hasta el flatten falla, se activa el kill-switch y se exige intervención.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.enums import AlertType, AuditAction
from trading_bot.db.models.broker_order import BrokerOrder
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.infrastructure.audit.logger import AuditLogger

logger = structlog.get_logger()

KIND_SUFFIX = {
    BrokerOrder.KIND_ENTRY: "e",
    BrokerOrder.KIND_SL: "sl",
    BrokerOrder.KIND_TP: "tp",
    BrokerOrder.KIND_FLATTEN: "fl",
    BrokerOrder.KIND_MANUAL_CLOSE: "mc",
}


@dataclass
class ExecutionOutcome:
    ok: bool
    trade_id: int | None = None
    entry_order_id: str | None = None
    sl_ok: bool = False
    tp_ok: bool = False
    flattened: bool = False
    message: str = ""


@dataclass
class FlattenResult:
    ok: bool
    order_id: str | None = None
    message: str = ""


class OrderExecutionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        broker: BinanceBroker | None = None,
        notifier: TelegramNotifier | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.broker = broker or BinanceBroker(self.settings)
        self.notifier = notifier or TelegramNotifier(self.settings)

    # ------------------------------------------------------------------
    # Helpers de intents
    # ------------------------------------------------------------------

    def client_order_id(self, trade_id: int, kind: str) -> str:
        return f"{self.settings.client_order_prefix}-{trade_id}-{KIND_SUFFIX[kind]}"

    async def _get_intent(self, client_order_id: str) -> BrokerOrder | None:
        result = await self.session.execute(
            select(BrokerOrder).where(BrokerOrder.client_order_id == client_order_id)
        )
        return result.scalar_one_or_none()

    async def _create_intent(
        self,
        *,
        trade: UserTrade,
        kind: str,
        side: str,
        order_type: str,
        amount: Decimal | None = None,
        trigger_price: Decimal | None = None,
        leverage: int | None = None,
    ) -> BrokerOrder:
        coid = self.client_order_id(trade.id, kind)
        intent = BrokerOrder(
            user_trade_id=trade.id,
            client_order_id=coid,
            kind=kind,
            symbol=trade.symbol,
            side=side,
            order_type=order_type,
            amount=amount,
            trigger_price=trigger_price,
            leverage=leverage,
            status=BrokerOrder.STATUS_INTENT,
        )
        self.session.add(intent)
        # Commit ANTES de tocar la red: si el proceso muere, el intent queda
        await self.session.commit()
        AuditLogger.log(
            "execution", AuditAction.ORDER_INTENT, f"{kind} {trade.symbol} {coid}", entity_id=trade.id
        )
        return intent

    async def _mark(self, intent: BrokerOrder, status: str, *, exchange_order_id: str | None = None,
                    error: str | None = None) -> None:
        intent.status = status
        if exchange_order_id:
            intent.exchange_order_id = exchange_order_id
        if error:
            intent.error = error[:1000]
        await self.session.commit()

    # ------------------------------------------------------------------
    # Apertura protegida
    # ------------------------------------------------------------------

    async def open_protected_position(
        self, *, trade: UserTrade, position_size_usdt: Decimal, leverage: int
    ) -> ExecutionOutcome:
        symbol = trade.symbol
        entry_side = "buy" if trade.direction == "LONG" else "sell"
        exit_side = "sell" if trade.direction == "LONG" else "buy"

        # 1) Idempotencia: ¿ya existe el intent de entrada?
        entry_coid = self.client_order_id(trade.id, BrokerOrder.KIND_ENTRY)
        entry_intent = await self._get_intent(entry_coid)

        if entry_intent is None:
            try:
                amount_str = await asyncio.to_thread(
                    self.broker._amount_from_position_usdt,
                    symbol,
                    position_size_usdt,
                    trade.entry_price,
                )
            except Exception as exc:
                return ExecutionOutcome(ok=False, trade_id=trade.id, message=f"Sizing inválido: {exc}")
            amount = Decimal(amount_str)
            if amount <= 0:
                return ExecutionOutcome(
                    ok=False, trade_id=trade.id, message="Tamaño de orden demasiado pequeño"
                )
            entry_intent = await self._create_intent(
                trade=trade,
                kind=BrokerOrder.KIND_ENTRY,
                side=entry_side,
                order_type="market",
                amount=amount,
                leverage=leverage,
            )

        # 2) Enviar entrada (o reanudar si quedó SENT de un crash anterior)
        if entry_intent.status in (BrokerOrder.STATUS_INTENT, BrokerOrder.STATUS_SENT):
            if entry_intent.status == BrokerOrder.STATUS_SENT:
                # Crash post-envío: consultar antes de reenviar
                existing = await asyncio.to_thread(
                    self.broker.fetch_order_by_client_id, symbol, entry_coid
                )
                if existing is not None:
                    await self._mark(
                        entry_intent,
                        BrokerOrder.STATUS_ACKED,
                        exchange_order_id=str(existing.get("id", "")),
                    )
                else:
                    await self._mark(entry_intent, BrokerOrder.STATUS_REJECTED,
                                     error="Intent SENT sin orden en exchange (nunca llegó)")
                    trade.status = "CANCELLED"
                    await self.session.commit()
                    return ExecutionOutcome(
                        ok=False, trade_id=trade.id,
                        message="Entrada anterior nunca llegó al exchange; trade cancelado",
                    )
            else:
                try:
                    await asyncio.to_thread(self.broker.set_leverage_safe, leverage, symbol)
                except Exception as exc:  # noqa: BLE001 — leverage previo puede seguir válido
                    logger.warning("set_leverage_failed", symbol=symbol, error=str(exc))
                await self._mark(entry_intent, BrokerOrder.STATUS_SENT)
                try:
                    order = await asyncio.to_thread(
                        self.broker.market_order,
                        symbol,
                        entry_side,
                        float(entry_intent.amount),
                        client_order_id=entry_coid,
                    )
                except Exception as exc:
                    # Ambiguo: ¿llegó o no? Consultar por clientOrderId
                    existing = None
                    try:
                        existing = await asyncio.to_thread(
                            self.broker.fetch_order_by_client_id, symbol, entry_coid
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    if existing is not None:
                        await self._mark(
                            entry_intent,
                            BrokerOrder.STATUS_ACKED,
                            exchange_order_id=str(existing.get("id", "")),
                        )
                    else:
                        await self._mark(entry_intent, BrokerOrder.STATUS_REJECTED, error=str(exc))
                        trade.status = "CANCELLED"
                        await self.session.commit()
                        AuditLogger.log(
                            "execution", AuditAction.ORDER_FAILED,
                            f"Entrada {symbol} falló: {exc}", entity_id=trade.id,
                        )
                        return ExecutionOutcome(
                            ok=False, trade_id=trade.id, message=f"Entrada falló: {exc}"
                        )
                else:
                    await self._mark(
                        entry_intent,
                        BrokerOrder.STATUS_ACKED,
                        exchange_order_id=str(order.get("id", "")),
                    )
            AuditLogger.log(
                "execution", AuditAction.ORDER_CONFIRMED,
                f"Entrada {symbol} confirmada ({entry_intent.exchange_order_id})", entity_id=trade.id,
            )

        # 3) SL con garantía (la parte más crítica)
        sl_ok = await self.ensure_stop_loss(trade)
        if not sl_ok:
            if self.settings.flatten_on_protection_failure:
                flatten = await self.flatten_trade(trade, "SL_PLACEMENT_FAILED")
                return ExecutionOutcome(
                    ok=False,
                    trade_id=trade.id,
                    entry_order_id=entry_intent.exchange_order_id,
                    flattened=flatten.ok,
                    message="SL imposible de colocar; posición aplanada"
                    if flatten.ok
                    else "CRÍTICO: SL y flatten fallaron — intervención manual",
                )
            await self._alert_protection_failed(trade, flattened=False)
            return ExecutionOutcome(
                ok=False,
                trade_id=trade.id,
                entry_order_id=entry_intent.exchange_order_id,
                message="SL falló y FLATTEN_ON_PROTECTION_FAILURE=false — posición SIN protección",
            )

        # 4) TP best-effort (ya hay SL: si falla solo alertamos)
        tp_ok = await self._place_tp_best_effort(trade, exit_side)

        return ExecutionOutcome(
            ok=True,
            trade_id=trade.id,
            entry_order_id=entry_intent.exchange_order_id,
            sl_ok=True,
            tp_ok=tp_ok,
            message="Posición abierta y protegida en Binance",
        )

    # ------------------------------------------------------------------
    # Protección
    # ------------------------------------------------------------------

    async def ensure_stop_loss(self, trade: UserTrade) -> bool:
        """Coloca el SL con retry agresivo. True si la posición queda protegida."""
        if not trade.stop_loss:
            return False
        exit_side = "sell" if trade.direction == "LONG" else "buy"
        sl_coid = self.client_order_id(trade.id, BrokerOrder.KIND_SL)
        sl_intent = await self._get_intent(sl_coid)
        if sl_intent is not None and sl_intent.status in (
            BrokerOrder.STATUS_ACKED,
            BrokerOrder.STATUS_FILLED,
        ):
            # Verificar que sigue activa en el exchange
            existing = None
            try:
                existing = await asyncio.to_thread(
                    self.broker.fetch_order_by_client_id, trade.symbol, sl_coid
                )
            except Exception:  # noqa: BLE001
                pass
            if existing is not None and existing.get("status") in ("open", "untriggered", None):
                return True

        if sl_intent is None:
            sl_intent = await self._create_intent(
                trade=trade,
                kind=BrokerOrder.KIND_SL,
                side=exit_side,
                order_type="stop_market",
                trigger_price=trade.stop_loss,
            )

        base = self.settings.sl_placement_backoff_base_seconds
        for attempt in range(self.settings.sl_placement_max_retries):
            try:
                await self._mark(sl_intent, BrokerOrder.STATUS_SENT)
                order = await asyncio.to_thread(
                    self.broker.place_stop_loss,
                    trade.symbol,
                    exit_side,
                    trade.stop_loss,
                    client_order_id=sl_coid,
                )
                await self._mark(
                    sl_intent, BrokerOrder.STATUS_ACKED, exchange_order_id=str(order.get("id", ""))
                )
                return True
            except Exception as exc:  # noqa: BLE001
                AuditLogger.log(
                    "execution",
                    AuditAction.PROTECTION_RETRY,
                    f"SL {trade.symbol} intento {attempt + 1} falló: {exc}",
                    entity_id=trade.id,
                )
                await self._mark(sl_intent, BrokerOrder.STATUS_UNKNOWN, error=str(exc))
                if attempt < self.settings.sl_placement_max_retries - 1:
                    delay = (2**attempt) * base + random.uniform(0, base)
                    await asyncio.sleep(delay)
        return False

    async def _place_tp_best_effort(self, trade: UserTrade, exit_side: str) -> bool:
        tp_price = trade.take_profit_2 or trade.take_profit_1
        if not tp_price:
            return False
        tp_coid = self.client_order_id(trade.id, BrokerOrder.KIND_TP)
        tp_intent = await self._get_intent(tp_coid)
        if tp_intent is not None and tp_intent.status in (
            BrokerOrder.STATUS_ACKED,
            BrokerOrder.STATUS_FILLED,
        ):
            return True
        if tp_intent is None:
            tp_intent = await self._create_intent(
                trade=trade,
                kind=BrokerOrder.KIND_TP,
                side=exit_side,
                order_type="take_profit_market",
                trigger_price=tp_price,
            )
        try:
            await self._mark(tp_intent, BrokerOrder.STATUS_SENT)
            order = await asyncio.to_thread(
                self.broker.place_take_profit,
                trade.symbol,
                exit_side,
                tp_price,
                client_order_id=tp_coid,
            )
            await self._mark(
                tp_intent, BrokerOrder.STATUS_ACKED, exchange_order_id=str(order.get("id", ""))
            )
            return True
        except Exception as exc:  # noqa: BLE001
            await self._mark(tp_intent, BrokerOrder.STATUS_UNKNOWN, error=str(exc))
            AuditLogger.log(
                "execution", AuditAction.ORDER_FAILED,
                f"TP {trade.symbol} falló (no crítico, hay SL): {exc}", entity_id=trade.id,
            )
            if self.notifier.is_configured:
                await self.notifier.send_alert(
                    AlertType.PROTECTION_FAILED,
                    symbol=trade.symbol,
                    direction=trade.direction,
                    extra=f"TP no colocado (la posición SÍ tiene SL): {exc}",
                )
            return False

    # ------------------------------------------------------------------
    # Flatten (última línea de defensa)
    # ------------------------------------------------------------------

    async def flatten_trade(self, trade: UserTrade, reason: str) -> FlattenResult:
        """Cierra la posición a mercado y cancela órdenes. Retry agresivo:
        es la última línea de defensa antes del kill-switch."""
        kind = (
            BrokerOrder.KIND_MANUAL_CLOSE if reason == "MANUAL_CLOSE" else BrokerOrder.KIND_FLATTEN
        )
        coid = self.client_order_id(trade.id, kind)
        intent = await self._get_intent(coid)
        if intent is None:
            exit_side = "sell" if trade.direction == "LONG" else "buy"
            intent = await self._create_intent(
                trade=trade, kind=kind, side=exit_side, order_type="market"
            )

        last_error = ""
        for attempt in range(self.settings.sl_placement_max_retries + 2):
            try:
                await self._mark(intent, BrokerOrder.STATUS_SENT)
                order = await asyncio.to_thread(
                    self.broker.close_position_market, trade.symbol, client_order_id=coid
                )
                await asyncio.to_thread(self.broker.cancel_all_orders, trade.symbol)
                order_id = str(order.get("id", "")) if order else None
                await self._mark(intent, BrokerOrder.STATUS_FILLED, exchange_order_id=order_id)

                trade.status = "CLOSED"
                trade.close_reason = "PROTECTION_FAILED" if kind == BrokerOrder.KIND_FLATTEN else reason
                trade.closed_at = datetime.now(UTC)
                await self.session.commit()

                AuditLogger.log(
                    "execution", AuditAction.POSITION_FLATTENED,
                    f"Posición {trade.symbol} aplanada ({reason})", entity_id=trade.id,
                )
                await self._alert_flattened(trade, reason)
                return FlattenResult(ok=True, order_id=order_id, message="Posición cerrada a mercado")
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                await self._mark(intent, BrokerOrder.STATUS_UNKNOWN, error=last_error)
                base = self.settings.sl_placement_backoff_base_seconds
                await asyncio.sleep((2**attempt) * base + random.uniform(0, base))

        # Flatten imposible: kill-switch automático + alerta crítica
        await self._engage_kill_switch_on_failure(trade, last_error)
        return FlattenResult(ok=False, message=f"Flatten falló: {last_error}")

    async def _engage_kill_switch_on_failure(self, trade: UserTrade, error: str) -> None:
        from trading_bot.db.init_db import ensure_bot_state

        state = await ensure_bot_state(self.session)
        state.kill_switch_engaged = True
        state.entries_paused = True
        state.kill_switch_reason = f"Flatten falló en {trade.symbol}: {error}"
        await self.session.commit()
        AuditLogger.log(
            "execution", AuditAction.KILL_SWITCH_ENGAGED,
            f"Kill-switch automático: flatten falló en {trade.symbol}", entity_id=trade.id,
        )
        if self.notifier.is_configured:
            await self.notifier.send_alert(
                AlertType.PROTECTION_FAILED,
                symbol=trade.symbol,
                direction=trade.direction,
                extra=(
                    "🆘 POSICIÓN SIN PROTECCIÓN — INTERVENCIÓN MANUAL REQUERIDA. "
                    f"Flatten falló: {error}. Kill-switch activado."
                ),
            )

    async def _alert_protection_failed(self, trade: UserTrade, *, flattened: bool) -> None:
        if not self.notifier.is_configured:
            return
        await self.notifier.send_alert(
            AlertType.PROTECTION_FAILED,
            symbol=trade.symbol,
            direction=trade.direction,
            extra="SL no colocado tras todos los reintentos."
            + (" Posición aplanada." if flattened else " ⚠️ Posición ABIERTA SIN SL."),
        )

    async def _alert_flattened(self, trade: UserTrade, reason: str) -> None:
        if not self.notifier.is_configured:
            return
        await self.notifier.send_alert(
            AlertType.POSITION_FLATTENED,
            symbol=trade.symbol,
            direction=trade.direction,
            extra=f"Cerrada a mercado. Motivo: {reason}",
        )
