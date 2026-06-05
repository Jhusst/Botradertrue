from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.enums import AlertType, AuditAction, TradeDirection
from trading_bot.db.models.account import Account
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.modules.ai_chart_analyzer.analyzer import AIChartAnalyzer
from trading_bot.modules.ai_chart_analyzer.feedback import AIFeedbackStore
from trading_bot.modules.audit_logger.logger import AuditLogger
from trading_bot.modules.execution_engine.engine import ExecutionEngine
from trading_bot.modules.telegram_alerts.notifier import TelegramNotifier
AI_VERDICT_RANK = {"DISAGREE": 0, "CAUTION": 1, "NEUTRAL": 2, "CONFIRM": 3}


@dataclass
class AutonomousResult:
    executed: bool
    trade_id: int | None = None
    broker_order_id: str | None = None
    message: str = ""
    ai_verdict: str | None = None
    blocked_reason: str | None = None


class AutonomousTraderService:
    """Entrada y salida automática sin intervención del usuario."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.notifier = TelegramNotifier(self.settings)
        self.ai = AIChartAnalyzer(self.settings)

    @property
    def is_enabled(self) -> bool:
        return self.settings.autonomous_trading_enabled

    def _ai_allows(self, verdict: str) -> bool:
        if not self.settings.ai_gate_auto_trade:
            return True
        if not self.settings.ai_enabled:
            return not self.settings.ai_required_for_auto_trade
        minimum = self.settings.ai_auto_min_verdict.upper()
        return AI_VERDICT_RANK.get(verdict.upper(), 0) >= AI_VERDICT_RANK.get(minimum, 3)

    async def _account_blocks(self, account: Account) -> str | None:
        min_bal = Decimal(str(self.settings.min_balance_for_autonomous))
        if account.balance_usdt < min_bal:
            return f"Balance ${account.balance_usdt} < mínimo ${min_bal} para modo autónomo."

        daily_limit = account.balance_usdt * Decimal(str(self.settings.max_daily_loss_percent)) / Decimal("100")
        if account.daily_pnl_usdt <= -daily_limit:
            return f"Pérdida diaria máxima alcanzada ({self.settings.max_daily_loss_percent}%)."

        weekly_limit = account.balance_usdt * Decimal(str(self.settings.max_weekly_loss_percent)) / Decimal("100")
        if account.weekly_pnl_usdt <= -weekly_limit:
            return f"Pérdida semanal máxima alcanzada ({self.settings.max_weekly_loss_percent}%)."

        if account.consecutive_losses >= self.settings.max_consecutive_losses:
            return (
                f"Bloqueado tras {account.consecutive_losses} pérdidas consecutivas. "
                f"Espera {self.settings.consecutive_loss_cooldown_hours}h."
            )
        return None

    async def process_entry(self, signal: Signal, current_price: Decimal) -> AutonomousResult:
        if not self.is_enabled:
            return AutonomousResult(executed=False, message="Modo autónomo desactivado")

        existing = await self.session.execute(
            select(UserTrade).where(
                UserTrade.signal_id == signal.id,
                UserTrade.status == "OPEN",
            )
        )
        if existing.scalar_one_or_none():
            return AutonomousResult(executed=False, message="Trade ya abierto para esta señal")

        acc_result = await self.session.execute(select(Account).where(Account.id == signal.account_id))
        account = acc_result.scalar_one_or_none()
        if not account:
            return AutonomousResult(executed=False, blocked_reason="Perfil no encontrado")

        block = await self._account_blocks(account)
        if block:
            AuditLogger.log("autonomous", AuditAction.RISK_BLOCKED, block, entity_id=signal.id)
            return AutonomousResult(executed=False, blocked_reason=block)

        ai_verdict: str | None = None
        ai_summary = ""
        if self.settings.ai_gate_auto_trade and self.settings.ai_enabled:
            store = AIFeedbackStore(self.session)
            few_shot = await store.get_few_shot_examples()
            analysis = await self.ai.analyze_setup(
                symbol=signal.symbol,
                direction=signal.direction,
                setup_grade=signal.setup_grade,
                technical_explanation=signal.technical_explanation or "",
                entry=str(signal.entry_price) if signal.entry_price else None,
                stop=str(signal.stop_loss) if signal.stop_loss else None,
                tp2=str(signal.take_profit_2) if signal.take_profit_2 else None,
                few_shot_examples=few_shot,
            )
            ai_verdict = analysis.verdict
            ai_summary = analysis.summary
            if not self._ai_allows(ai_verdict):
                msg = f"IA bloqueó auto-trade: {ai_verdict} — {ai_summary}"
                AuditLogger.log("autonomous", AuditAction.SIGNAL_REJECTED, msg, entity_id=signal.id)
                await self._notify_blocked(signal, current_price, msg)
                return AutonomousResult(
                    executed=False,
                    blocked_reason=msg,
                    ai_verdict=ai_verdict,
                )
        elif self.settings.ai_required_for_auto_trade and not self.settings.ai_enabled:
            return AutonomousResult(
                executed=False,
                blocked_reason="IA obligatoria pero AI_ENABLED=false",
            )

        return await self._open_and_execute(signal, account, current_price, ai_verdict, ai_summary)

    async def _open_and_execute(
        self,
        signal: Signal,
        account: Account,
        current_price: Decimal,
        ai_verdict: str | None,
        ai_summary: str,
    ) -> AutonomousResult:
        margin = signal.margin_required or Decimal("0")
        trade = UserTrade(
            account_id=account.id,
            signal_id=signal.id,
            symbol=signal.symbol,
            direction=signal.direction,
            status="OPEN",
            entry_price=signal.entry_price or current_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            margin_used=margin,
            leverage=signal.recommended_leverage or 1,
            risk_usdt=signal.risk_usdt or Decimal("0"),
            notes=f"auto-entry @ {current_price}" + (f" | IA:{ai_verdict}" if ai_verdict else ""),
        )
        self.session.add(trade)
        await self.session.flush()

        broker_order_id: str | None = None
        broker_msg = ""
        engine = ExecutionEngine()
        position_usdt = signal.position_size or (margin * Decimal(str(trade.leverage)))

        if self.settings.broker_enabled and self.settings.live_mode_enabled:
            try:
                result = engine.execute(
                    symbol=signal.symbol,
                    direction=signal.direction,
                    entry_price=signal.entry_price or current_price,
                    position_size_usdt=position_usdt,
                    leverage=trade.leverage,
                    stop_loss=signal.stop_loss,
                    take_profit_1=signal.take_profit_1,
                )
                if result.ok:
                    broker_order_id = result.order_id
                    trade.notes = (trade.notes or "") + f" | Binance {broker_order_id}"
                    broker_msg = result.message
                else:
                    broker_msg = result.message
            except Exception as exc:
                broker_msg = str(exc)

        if self.settings.sync_balance_from_broker and broker_order_id:
            await self._sync_balance(account)

        extra = (
            f"🤖 AUTO | Perfil {account.name} | IA: {ai_verdict or 'sin IA'} | "
            f"{ai_summary[:80] if ai_summary else ''} | Broker: {broker_order_id or broker_msg or 'paper/local'}"
        )
        await self._send_autonomous_alert(signal, current_price, extra)

        AuditLogger.log(
            "autonomous",
            AuditAction.PAPER_OPENED if not broker_order_id else AuditAction.LIVE_ENABLED,
            f"Auto-entry {signal.symbol} trade#{trade.id}",
            entity_id=signal.id,
        )

        return AutonomousResult(
            executed=True,
            trade_id=trade.id,
            broker_order_id=broker_order_id,
            message=broker_msg or "Trade autónomo registrado",
            ai_verdict=ai_verdict,
        )

    async def _sync_balance(self, account: Account) -> None:
        from trading_bot.modules.execution_engine.binance_broker import BinanceBroker

        broker = BinanceBroker(self.settings)
        snap = broker.fetch_account()
        if snap.connected and snap.available_balance:
            account.balance_usdt = Decimal(snap.available_balance)

    async def _send_autonomous_alert(self, signal: Signal, price: Decimal, extra: str) -> None:
        if not self.notifier.is_configured:
            return
        message = self.notifier._format_alert(
            alert_type=AlertType.AUTONOMOUS_ENTRY,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            current_price=price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            extra=extra,
            signal_id=signal.id,
        )
        await self.notifier.send_raw(message, urgent=True)

    async def _notify_blocked(self, signal: Signal, price: Decimal, reason: str) -> None:
        if not self.notifier.is_configured:
            return
        message = self.notifier._format_alert(
            alert_type=AlertType.AI_BLOCKED,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            current_price=price,
            stop_loss=signal.stop_loss,
            extra=reason,
            signal_id=signal.id,
        )
        await self.notifier.send_raw(message, urgent=False)

    async def update_open_trades(self, symbol: str, current_price: Decimal) -> list[tuple[UserTrade, str]]:
        """Cierra trades locales cuando precio toca SL/TP (Binance también tiene órdenes reduceOnly)."""
        result = await self.session.execute(
            select(UserTrade).where(UserTrade.symbol == symbol, UserTrade.status == "OPEN")
        )
        trades = result.scalars().all()
        events: list[tuple[UserTrade, str]] = []

        for trade in trades:
            event = self._check_exit(trade, current_price)
            if not event:
                continue

            pnl = self._estimate_pnl(trade, current_price)
            trade.status = "CLOSED"
            trade.exit_price = current_price
            trade.pnl_usdt = pnl
            trade.close_reason = event
            from datetime import UTC, datetime

            trade.closed_at = datetime.now(UTC)

            acc_result = await self.session.execute(select(Account).where(Account.id == trade.account_id))
            account = acc_result.scalar_one()
            account.balance_usdt += pnl
            account.daily_pnl_usdt += pnl
            account.weekly_pnl_usdt += pnl
            if pnl < 0:
                account.consecutive_losses += 1
            else:
                account.consecutive_losses = 0

            if self.settings.compound_balance_on_close and self.settings.sync_balance_from_broker:
                await self._sync_balance(account)

            events.append((trade, event))

        return events

    @staticmethod
    def _check_exit(trade: UserTrade, price: Decimal) -> str | None:
        if trade.direction == TradeDirection.LONG.value:
            if trade.stop_loss and price <= trade.stop_loss:
                return "STOP_LOSS"
            if trade.take_profit_2 and price >= trade.take_profit_2:
                return "TAKE_PROFIT"
            if trade.take_profit_1 and price >= trade.take_profit_1:
                return "TP1"
        elif trade.direction == TradeDirection.SHORT.value:
            if trade.stop_loss and price >= trade.stop_loss:
                return "STOP_LOSS"
            if trade.take_profit_2 and price <= trade.take_profit_2:
                return "TAKE_PROFIT"
            if trade.take_profit_1 and price <= trade.take_profit_1:
                return "TP1"
        return None

    @staticmethod
    def _estimate_pnl(trade: UserTrade, exit_price: Decimal) -> Decimal:
        diff = exit_price - trade.entry_price
        if trade.direction == TradeDirection.SHORT.value:
            diff = -diff
        if trade.entry_price == 0:
            return Decimal("0")
        notional = trade.margin_used * Decimal(str(trade.leverage))
        return (notional * diff / trade.entry_price).quantize(Decimal("0.01"))
