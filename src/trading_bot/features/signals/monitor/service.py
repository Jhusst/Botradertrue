from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.enums import AlertType, AuditAction, SignalStatus, TradeDirection
from trading_bot.db.models.account import Account
from trading_bot.db.models.alert_log import AlertLog
from trading_bot.db.models.signal import Signal
from trading_bot.db.seed_profiles import ensure_profiles
from trading_bot.infrastructure.audit.logger import AuditLogger
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector
from trading_bot.features.autonomous.service import AutonomousTraderService
from trading_bot.features.trades.paper.service import PaperTradingService
from trading_bot.features.signals.generator import SignalGenerator
from trading_bot.features.signals.monitor.price_feed import PriceFeed
from trading_bot.features.signals.strategies.trend_pullback_mvp import MarketContext
from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.schemas.risk import AccountRiskState
from trading_bot.schemas.signal import SignalCreate


class SignalMonitorService:
    """Escanea mercados, vigila señales activas y envía alertas en tiempo real."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings or get_settings()
        self.notifier = TelegramNotifier(self.settings)
        self.price_feed = PriceFeed(use_live=self.settings.monitor_use_live_data)
        self.generator = SignalGenerator()
        self._running = False
        self._last_scan: datetime | None = None
        self._last_price_check: datetime | None = None
        self._last_reconcile: datetime | None = None
        self._last_daily_data_job: datetime | None = None
        self._cycles = 0

    @property
    def watch_symbols(self) -> list[str]:
        return [s.strip() for s in self.settings.watch_symbols.split(",") if s.strip()]

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def status(self) -> dict:
        return {
            "running": self._running,
            "symbols": self.watch_symbols,
            "scan_interval_seconds": self.settings.scan_interval_seconds,
            "price_check_interval_seconds": self.settings.price_check_interval_seconds,
            "telegram_configured": self.notifier.is_configured,
            "auto_paper_trade": self.settings.auto_paper_trade,
            "autonomous_trading": self.settings.autonomous_trading_enabled,
            "ai_gate": self.settings.ai_gate_auto_trade,
            "use_live_data": self.settings.monitor_use_live_data,
            "last_scan": self._last_scan.isoformat() if self._last_scan else None,
            "last_price_check": self._last_price_check.isoformat() if self._last_price_check else None,
            "cycles": self._cycles,
        }

    async def run_cycle(self) -> dict:
        """Un ciclo completo: escanear + vigilar precios + reconciliar contra el exchange."""
        self._cycles += 1
        now = datetime.now(UTC)
        scanned = 0
        alerts_sent = 0
        reconciled = 0

        if self._should_scan(now):
            scanned = await self._scan_symbols()
            self._last_scan = now

        if self._should_check_prices(now):
            alerts_sent = await self._watch_active_signals()
            self._last_price_check = now

        if self._should_reconcile(now):
            reconciled = await self._run_reconciliation()
            self._last_reconcile = now

        if self._should_run_daily_data_job(now):
            await self._run_daily_data_job()
            self._last_daily_data_job = now

        return {
            "scanned": scanned,
            "alerts_sent": alerts_sent,
            "reconciled": reconciled,
            "cycle": self._cycles,
        }

    def _should_run_daily_data_job(self, now: datetime) -> bool:
        if not (self.settings.derivatives_enabled and self.settings.monitor_use_live_data):
            return False
        if not self._last_daily_data_job:
            return True
        return (now - self._last_daily_data_job).total_seconds() >= 86_400

    async def _run_daily_data_job(self) -> None:
        """Acumula histórico y derivados en cache local (crítico: Binance solo
        expone 30 días de long/short ratio — hay que acumularlos desde ya)."""
        import asyncio

        from trading_bot.infrastructure.market_data.derivatives_client import DerivativesDataClient
        from trading_bot.infrastructure.market_data.history_store import HistoryStore

        try:
            store = HistoryStore()
            derivatives = DerivativesDataClient()
            for symbol in self.watch_symbols:
                for timeframe in ("4h", "1h", "15m"):
                    await asyncio.to_thread(store.update, symbol, timeframe)
                await asyncio.to_thread(derivatives.accumulate, symbol)
        except Exception as exc:  # noqa: BLE001 — el job de datos nunca tumba el monitor
            AuditLogger.log(
                "signal_monitor", AuditAction.RECONCILE_ALERT, f"Job diario de datos falló: {exc}"
            )

    def _should_reconcile(self, now: datetime) -> bool:
        if not (self.settings.broker_enabled and self.settings.binance_api_key):
            return False
        if not self._last_reconcile:
            return True
        return (now - self._last_reconcile).total_seconds() >= self.settings.reconcile_interval_seconds

    async def _run_reconciliation(self) -> int:
        from trading_bot.features.reconciliation.service import ReconciliationService

        try:
            async with self.session_factory() as session:
                report = await ReconciliationService(session, self.settings).run()
                return report.fixed
        except Exception as exc:  # noqa: BLE001
            AuditLogger.log(
                "signal_monitor", AuditAction.RECONCILE_ALERT, f"Error reconciliando: {exc}"
            )
            return 0

    def _should_scan(self, now: datetime) -> bool:
        if not self._last_scan:
            return True
        return (now - self._last_scan).total_seconds() >= self.settings.scan_interval_seconds

    def _should_check_prices(self, now: datetime) -> bool:
        if not self._last_price_check:
            return True
        return (now - self._last_price_check).total_seconds() >= self.settings.price_check_interval_seconds

    async def _scan_symbols(self) -> int:
        count = 0
        async with self.session_factory() as session:
            profiles = await ensure_profiles(session)

            trade_stats = None
            if self.settings.kelly_enabled:
                from trading_bot.features.signals.risk import TradeStatsProvider

                try:
                    trade_stats = await TradeStatsProvider(self.settings).get_stats(session)
                except Exception:  # noqa: BLE001 — Kelly es opcional, nunca rompe el scan
                    trade_stats = None

            for symbol in self.watch_symbols:
                try:
                    data = self.price_feed.get_market_data(symbol)
                    ctx = MarketContext(symbol=symbol, df_4h=data["4h"], df_1h=data["1h"], df_15m=data["15m"])
                except Exception as exc:
                    AuditLogger.log(
                        "signal_monitor",
                        AuditAction.SIGNAL_REJECTED,
                        f"Error obteniendo datos {symbol}: {exc}",
                    )
                    continue

                if self.settings.regime_detection_enabled:
                    try:
                        from trading_bot.features.regime import RegimeDetector

                        ctx.regime = RegimeDetector().detect(ctx.df_4h, ctx.df_1h)
                    except Exception:  # noqa: BLE001 — régimen es opcional
                        ctx.regime = None

                if self.settings.derivatives_enabled and self.settings.monitor_use_live_data:
                    try:
                        from trading_bot.infrastructure.market_data.derivatives_client import (
                            DerivativesDataClient,
                        )

                        ctx.derivatives = DerivativesDataClient().snapshot(symbol)
                    except Exception:  # noqa: BLE001 — alt-data es opcional
                        ctx.derivatives = None

                for profile in profiles:
                    if await self._has_recent_signal(session, symbol, profile.id):
                        continue
                    account = self._profile_to_risk_state(profile)
                    signal_data = self.generator.generate(ctx, account, trade_stats=trade_stats)
                    signal_data.symbol = symbol
                    if signal_data.should_trade:
                        saved = await self._save_signal(session, signal_data, profile.id)
                        profile_label = profile.name
                        await self._send_alert_once(
                            session,
                            saved.id,
                            AlertType.NEW_SIGNAL,
                            saved,
                            extra=(
                                f"Perfil: {profile_label} | Riesgo: {saved.risk_percent}% "
                                f"(${saved.risk_usdt} USDT) | Margen: ${saved.margin_required}"
                            ),
                        )
                        count += 1
                        AuditLogger.log(
                            "signal_monitor",
                            AuditAction.SIGNAL_GENERATED,
                            f"Nueva señal {symbol} {saved.direction} [{profile_label}]",
                            entity_type="signal",
                            entity_id=saved.id,
                        )
            await session.commit()
        return count

    async def _watch_active_signals(self) -> int:
        alerts = 0
        async with self.session_factory() as session:
            result = await session.execute(
                select(Signal).where(
                    Signal.should_trade.is_(True),
                    Signal.status.in_([SignalStatus.WATCHING.value, SignalStatus.ACTIVE.value]),
                )
            )
            signals = result.scalars().all()
            paper_service = PaperTradingService(session)
            auto_trader = AutonomousTraderService(session, self.settings)

            for signal in signals:
                try:
                    price = self.price_feed.get_price(signal.symbol)
                    signal.last_price = price

                    if signal.expires_at and datetime.now(UTC) > signal.expires_at.replace(tzinfo=UTC):
                        signal.status = SignalStatus.EXPIRED.value
                        if await self._send_alert_once(session, signal.id, AlertType.SIGNAL_EXPIRED, signal):
                            alerts += 1
                        continue

                    if await self._check_invalidation(session, signal, price):
                        alerts += 1
                        continue

                    if signal.status == SignalStatus.WATCHING.value:
                        alerts += await self._handle_watching(session, signal, price, paper_service)

                    if signal.status == SignalStatus.ACTIVE.value:
                        events = await paper_service.update_open_trades(signal.symbol, price)
                        for trade, event in events:
                            if event == "STOP_LOSS":
                                if await self._send_trade_alert(session, signal, AlertType.STOP_LOSS, trade):
                                    alerts += 1
                                signal.status = SignalStatus.CLOSED.value
                            elif event == "TAKE_PROFIT":
                                if await self._send_trade_alert(session, signal, AlertType.TAKE_PROFIT, trade):
                                    alerts += 1
                                signal.status = SignalStatus.CLOSED.value
                            elif event == "TP1":
                                if await self._send_trade_alert(
                                    session, signal, AlertType.TAKE_PROFIT, trade, extra="TP1 alcanzado"
                                ):
                                    alerts += 1

                        user_events = await auto_trader.update_open_trades(signal.symbol, price)
                        for utrade, event in user_events:
                            extra = f"P&L est.: ${utrade.pnl_usdt} USDT"
                            alert_type = (
                                AlertType.STOP_LOSS if event == "STOP_LOSS" else AlertType.TAKE_PROFIT
                            )
                            if await self._send_user_trade_alert(session, signal, alert_type, utrade, extra):
                                alerts += 1
                            if event in ("STOP_LOSS", "TAKE_PROFIT"):
                                signal.status = SignalStatus.CLOSED.value

                except Exception as exc:
                    AuditLogger.log(
                        "signal_monitor",
                        AuditAction.SIGNAL_REJECTED,
                        f"Error vigilando señal {signal.id}: {exc}",
                        entity_id=signal.id,
                    )

            await session.commit()
        return alerts

    async def _handle_watching(
        self,
        session: AsyncSession,
        signal: Signal,
        price: Decimal,
        paper_service: PaperTradingService,
    ) -> int:
        alerts = 0
        if not signal.entry_price:
            return 0

        proximity = Decimal(str(self.settings.entry_proximity_percent))
        distance_pct = abs(price - signal.entry_price) / signal.entry_price * Decimal("100")

        if distance_pct <= proximity:
            if await self._send_alert_once(
                session,
                signal.id,
                AlertType.ENTRY_APPROACHING,
                signal,
                current_price=price,
            ):
                alerts += 1

        if self._entry_hit(signal, price):
            if await self._send_alert_once(
                session,
                signal.id,
                AlertType.ENTRY_NOW,
                signal,
                current_price=price,
                urgent=True,
            ):
                alerts += 1

            signal.status = SignalStatus.ACTIVE.value
            AuditLogger.log(
                "signal_monitor",
                AuditAction.ENTRY_HIT,
                f"Entrada alcanzada {signal.symbol} @ {price}",
                entity_id=signal.id,
            )

            if self.settings.autonomous_trading_enabled:
                result = await AutonomousTraderService(session, self.settings).process_entry(signal, price)
                if result.blocked_reason:
                    if await self._send_alert_once(
                        session,
                        signal.id,
                        AlertType.AI_BLOCKED,
                        signal,
                        current_price=price,
                        extra=result.blocked_reason,
                    ):
                        alerts += 1
            elif self.settings.auto_paper_trade:
                trade = await paper_service.open_from_signal(signal)
                if trade:
                    if await self._send_alert_once(
                        session,
                        signal.id,
                        AlertType.PAPER_OPENED,
                        signal,
                        current_price=price,
                        extra=f"Paper trade #{trade.id} abierto automáticamente.",
                    ):
                        alerts += 1

        return alerts

    @staticmethod
    def _entry_hit(signal: Signal, price: Decimal) -> bool:
        if not signal.entry_price:
            return False
        if signal.direction == TradeDirection.LONG.value:
            return price <= signal.entry_price
        if signal.direction == TradeDirection.SHORT.value:
            return price >= signal.entry_price
        return False

    async def _check_invalidation(self, session: AsyncSession, signal: Signal, price: Decimal) -> bool:
        if not signal.stop_loss or signal.status != SignalStatus.WATCHING.value:
            return False

        invalidated = False
        if signal.direction == TradeDirection.LONG.value and price <= signal.stop_loss:
            invalidated = True
        elif signal.direction == TradeDirection.SHORT.value and price >= signal.stop_loss:
            invalidated = True

        if invalidated:
            signal.status = SignalStatus.INVALIDATED.value
            return await self._send_alert_once(
                session,
                signal.id,
                AlertType.SIGNAL_INVALIDATED,
                signal,
                current_price=price,
                extra="El precio tocó el stop antes de la entrada.",
            )
        return False

    async def _has_recent_signal(self, session: AsyncSession, symbol: str, account_id: int) -> bool:
        cutoff = datetime.now(UTC) - timedelta(minutes=self.settings.dedup_signal_minutes)
        result = await session.execute(
            select(func.count())
            .select_from(Signal)
            .where(
                and_(
                    Signal.symbol == symbol,
                    Signal.account_id == account_id,
                    Signal.should_trade.is_(True),
                    Signal.status.in_(
                        [SignalStatus.WATCHING.value, SignalStatus.ACTIVE.value, SignalStatus.PENDING.value]
                    ),
                    Signal.created_at >= cutoff,
                )
            )
        )
        return (result.scalar() or 0) > 0

    async def _save_signal(self, session: AsyncSession, data: SignalCreate, account_id: int) -> Signal:
        expires = datetime.now(UTC) + timedelta(hours=self.settings.signal_ttl_hours)
        signal = Signal(
            account_id=account_id,
            symbol=data.symbol,
            direction=data.direction.value,
            primary_timeframe=data.primary_timeframe,
            entry_price=data.entry_price,
            stop_loss=data.stop_loss,
            take_profit_1=data.take_profit_1,
            take_profit_2=data.take_profit_2,
            risk_reward_ratio=data.risk_reward_ratio,
            account_balance=data.account_balance,
            risk_percent=data.risk_percent,
            risk_usdt=data.risk_usdt,
            recommended_capital_usdt=data.recommended_capital_usdt,
            recommended_leverage=data.recommended_leverage,
            max_loss_usdt=data.max_loss_usdt,
            estimated_gain_tp1_usdt=data.estimated_gain_tp1_usdt,
            estimated_gain_tp2_usdt=data.estimated_gain_tp2_usdt,
            position_size=data.position_size,
            margin_required=data.margin_required,
            stop_distance_percent=data.stop_distance_percent,
            tp1_distance_percent=data.tp1_distance_percent,
            tp2_distance_percent=data.tp2_distance_percent,
            liquidation_price=data.liquidation_price,
            setup_grade=data.setup_grade.value,
            confidence_score=data.confidence_score,
            technical_explanation=data.technical_explanation,
            invalidation_conditions=data.invalidation_conditions,
            should_trade=True,
            status=SignalStatus.WATCHING.value,
            strategy_name=data.strategy_name,
            ml_probability=Decimal(str(data.ml_probability)) if data.ml_probability is not None else None,
            ml_model_version=data.ml_model_version,
            expires_at=expires,
        )
        session.add(signal)
        await session.flush()
        return signal

    async def _send_alert_once(
        self,
        session: AsyncSession,
        signal_id: int,
        alert_type: AlertType,
        signal: Signal,
        current_price: Decimal | None = None,
        extra: str | None = None,
        urgent: bool = False,
    ) -> bool:
        existing = await session.execute(
            select(AlertLog).where(
                AlertLog.signal_id == signal_id,
                AlertLog.alert_type == alert_type.value,
            )
        )
        if existing.scalar_one_or_none():
            return False

        message = self.notifier._format_alert(
            alert_type=alert_type,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_price=signal.entry_price,
            current_price=current_price or signal.last_price,
            stop_loss=signal.stop_loss,
            take_profit_1=signal.take_profit_1,
            take_profit_2=signal.take_profit_2,
            extra=extra,
            signal_id=signal_id,
        )
        delivered = await self.notifier.send_raw(message, urgent=urgent)

        log = AlertLog(
            signal_id=signal_id,
            alert_type=alert_type.value,
            message=message,
            delivered=delivered,
        )
        session.add(log)
        AuditLogger.log("telegram", AuditAction.ALERT_SENT, alert_type.value, entity_id=signal_id)
        return delivered

    async def _send_trade_alert(self, session, signal, alert_type, trade, extra=None) -> bool:
        msg_extra = extra or f"P&L: ${trade.pnl_usdt} USDT"
        return await self._send_alert_once(
            session, signal.id, alert_type, signal, current_price=trade.exit_price, extra=msg_extra
        )

    async def _send_user_trade_alert(self, session, signal, alert_type, trade, extra=None) -> bool:
        return await self._send_alert_once(
            session,
            signal.id,
            alert_type,
            signal,
            current_price=trade.exit_price,
            extra=extra or f"P&L: ${trade.pnl_usdt} USDT",
        )

    @staticmethod
    def _profile_to_risk_state(profile: Account) -> AccountRiskState:
        return AccountRiskState(
            balance_usdt=profile.balance_usdt,
            daily_pnl_usdt=profile.daily_pnl_usdt,
            weekly_pnl_usdt=profile.weekly_pnl_usdt,
            consecutive_losses=profile.consecutive_losses,
            current_drawdown_percent=profile.max_drawdown_percent,
            profile_type=profile.profile_type,
            risk_setup_a=profile.risk_setup_a,
            risk_setup_b=profile.risk_setup_b,
            max_leverage=profile.max_leverage,
            min_setup_grade=profile.min_setup_grade,
        )
