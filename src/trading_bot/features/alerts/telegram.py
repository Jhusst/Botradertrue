from decimal import Decimal

import httpx

from trading_bot.config.settings import Settings, get_settings
from trading_bot.core.enums import AlertType, TradeDirection
from trading_bot.schemas.signal import SignalCreate, SignalResponse


class TelegramNotifier:
    """Envía alertas de señales al chat configurado."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self.settings.telegram_bot_token and self.settings.telegram_chat_id)

    async def send_raw(self, message: str, urgent: bool = False) -> bool:
        if not self.is_configured:
            return False
        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": self.settings.telegram_chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "disable_notification": not urgent,
                },
            )
            return response.status_code == 200

    async def send_signal(self, signal: SignalCreate | SignalResponse, urgent: bool = False) -> bool:
        return await self.send_raw(self._format_signal(signal), urgent=urgent)

    async def send_alert(
        self,
        alert_type: AlertType,
        symbol: str,
        direction: str,
        entry_price: Decimal | None = None,
        current_price: Decimal | None = None,
        stop_loss: Decimal | None = None,
        take_profit_1: Decimal | None = None,
        take_profit_2: Decimal | None = None,
        extra: str | None = None,
        signal_id: int | None = None,
    ) -> bool:
        message = self._format_alert(
            alert_type=alert_type,
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            current_price=current_price,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            extra=extra,
            signal_id=signal_id,
        )
        urgent = alert_type in {
            AlertType.ENTRY_NOW,
            AlertType.ENTRY_APPROACHING,
            AlertType.STOP_LOSS,
            AlertType.PROTECTION_FAILED,
            AlertType.POSITION_FLATTENED,
            AlertType.KILL_SWITCH,
            AlertType.RECONCILE_MISMATCH,
            AlertType.CIRCUIT_BREAKER,
            AlertType.WATCHDOG_RESTART,
        }
        return await self.send_raw(message, urgent=urgent)

    def _format_alert(
        self,
        alert_type: AlertType,
        symbol: str,
        direction: str,
        entry_price: Decimal | None,
        current_price: Decimal | None,
        stop_loss: Decimal | None,
        take_profit_1: Decimal | None,
        take_profit_2: Decimal | None,
        extra: str | None,
        signal_id: int | None,
    ) -> str:
        sid = f" #{signal_id}" if signal_id else ""
        base = f"<b>{symbol}</b> {direction}{sid}\n"

        if alert_type == AlertType.ENTRY_NOW:
            return (
                f"🚨🚨 <b>ENTRA AHORA</b> 🚨🚨\n{base}"
                f"Precio actual: <code>{current_price}</code>\n"
                f"Entrada: <code>{entry_price}</code>\n"
                f"SL: <code>{stop_loss}</code> | TP1: <code>{take_profit_1}</code> | TP2: <code>{take_profit_2}</code>\n"
                f"⏱ La ventana de entrada está activa. No esperes."
            )
        if alert_type == AlertType.ENTRY_APPROACHING:
            dist = ""
            if entry_price and current_price and entry_price > 0:
                dist_pct = abs(current_price - entry_price) / entry_price * 100
                dist = f"Distancia: {dist_pct:.2f}%\n"
            return (
                f"⚠️ <b>PRECIO CERCA DE ENTRADA</b>\n{base}"
                f"Precio: <code>{current_price}</code> → Entrada: <code>{entry_price}</code>\n"
                f"{dist}Prepárate para entrar."
            )
        if alert_type == AlertType.NEW_SIGNAL:
            return (
                f"📊 <b>NUEVA SEÑAL OPERABLE</b>\n{base}"
                f"Entrada: <code>{entry_price}</code>\n"
                f"SL: <code>{stop_loss}</code>\n"
                f"TP1: <code>{take_profit_1}</code> | TP2: <code>{take_profit_2}</code>\n"
                f"{extra or ''}"
            )
        if alert_type == AlertType.PAPER_OPENED:
            return (
                f"📝 <b>PAPER TRADE ABIERTO</b>\n{base}"
                f"Entrada ejecutada: <code>{entry_price}</code>\n"
                f"{extra or ''}"
            )
        if alert_type == AlertType.TAKE_PROFIT:
            return f"✅ <b>TAKE PROFIT</b>\n{base}{extra or ''}"
        if alert_type == AlertType.STOP_LOSS:
            return f"🔴 <b>STOP LOSS</b>\n{base}{extra or ''}"
        if alert_type == AlertType.SIGNAL_EXPIRED:
            return f"⏰ <b>SEÑAL EXPIRADA</b>\n{base}La oportunidad ya no está vigente."
        if alert_type == AlertType.SIGNAL_INVALIDATED:
            return f"❌ <b>SEÑAL INVALIDADA</b>\n{base}{extra or 'Condiciones rotas.'}"
        if alert_type == AlertType.AUTONOMOUS_ENTRY:
            return (
                f"🤖 <b>TRADE AUTÓNOMO EJECUTADO</b>\n{base}"
                f"Precio: <code>{current_price}</code>\n"
                f"SL: <code>{stop_loss}</code> | TP1: <code>{take_profit_1}</code>\n"
                f"{extra or ''}"
            )
        if alert_type == AlertType.AI_BLOCKED:
            return f"🧠 <b>IA BLOQUEÓ AUTO-TRADE</b>\n{base}{extra or ''}"
        if alert_type == AlertType.PROTECTION_FAILED:
            return f"🆘 <b>FALLO DE PROTECCIÓN</b>\n{base}{extra or ''}"
        if alert_type == AlertType.POSITION_FLATTENED:
            return f"🧯 <b>POSICIÓN CERRADA A MERCADO</b>\n{base}{extra or ''}"
        if alert_type == AlertType.KILL_SWITCH:
            return f"🛑 <b>KILL-SWITCH</b>\n{base}{extra or ''}"
        if alert_type == AlertType.RECONCILE_MISMATCH:
            return f"⚖️ <b>DIVERGENCIA DB↔EXCHANGE</b>\n{base}{extra or ''}"
        if alert_type == AlertType.CIRCUIT_BREAKER:
            return f"🔌 <b>CIRCUIT BREAKER ABIERTO</b>\n{base}{extra or ''}"
        if alert_type == AlertType.WATCHDOG_RESTART:
            return f"🐶 <b>WATCHDOG REINICIÓ EL MONITOR</b>\n{base}{extra or ''}"
        if alert_type == AlertType.PROCESS_RESTARTED:
            return f"🔄 <b>PROCESO REINICIADO</b>\n{base}{extra or ''}"
        if alert_type == AlertType.MANUAL_CLOSED:
            return f"✋ <b>CIERRE MANUAL</b>\n{base}{extra or ''}"

        return f"ℹ️ {alert_type.value}\n{base}{extra or ''}"

    def _format_signal(self, signal: SignalCreate | SignalResponse) -> str:
        if signal.direction == TradeDirection.NO_TRADE or not signal.should_trade:
            return (
                f"🚫 <b>NO TRADE</b> — {getattr(signal, 'symbol', 'N/A')}\n"
                f"Motivo: {signal.rejection_reason or signal.technical_explanation}\n"
                f"Balance: ${signal.account_balance} USDT"
            )

        operate = "✅ Sí" if signal.should_trade else "❌ No"
        return (
            f"📊 <b>SEÑAL {signal.direction}</b> — {signal.symbol}\n"
            f"TF: {signal.primary_timeframe} | Setup: {signal.setup_grade}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Entrada: <code>{signal.entry_price}</code>\n"
            f"Stop Loss: <code>{signal.stop_loss}</code>\n"
            f"TP1: <code>{signal.take_profit_1}</code>\n"
            f"TP2: <code>{signal.take_profit_2}</code>\n"
            f"R:R: 1:{signal.risk_reward_ratio}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Balance: ${signal.account_balance} USDT\n"
            f"Riesgo: {signal.risk_percent}% (${signal.risk_usdt} USDT)\n"
            f"Capital: ${signal.recommended_capital_usdt} USDT\n"
            f"Apalancamiento: {signal.recommended_leverage}x\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Pérdida máx: ${signal.max_loss_usdt} USDT\n"
            f"💰 Ganancia TP1: ${signal.estimated_gain_tp1_usdt} USDT\n"
            f"💰 Ganancia TP2: ${signal.estimated_gain_tp2_usdt} USDT\n"
            f"Liquidación ~: {signal.liquidation_price or 'N/A'}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Confianza: {signal.confidence_score}% ({signal.setup_grade})\n"
            f"Motivo: {signal.technical_explanation}\n"
            f"Invalidación: {signal.invalidation_conditions}\n"
            f"¿Operar?: {operate}"
        )
