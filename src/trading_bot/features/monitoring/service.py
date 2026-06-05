import asyncio
import time
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import Settings, get_settings
from trading_bot.db.models.alert_log import AlertLog
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.trade import PaperTrade
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.features.ai.analyzer import AIChartAnalyzer
from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.infrastructure.workers.background import get_monitor

_HEALTH_CACHE_TTL_SECONDS = 25
_health_cache: tuple[dict, float] | None = None

CLOSE_REASON_LABELS = {
    "STOP_LOSS": "Stop Loss",
    "TAKE_PROFIT": "Take Profit (TP2)",
    "TP1": "Take Profit 1 (parcial)",
    "SIGNAL_EXPIRED": "Señal caducó",
    "MANUAL": "Cierre manual",
    "INVALIDATED": "Setup invalidado",
}


def trade_source(notes: str | None) -> str:
    if not notes:
        return "manual"
    if "auto-entry" in notes:
        return "auto"
    if notes.startswith("manual|"):
        return "manual"
    return "other"


def lifecycle_status(trade: UserTrade, signal: Signal | None) -> str:
    if trade.status == "OPEN":
        if signal and signal.status == "EXPIRED":
            return "OPEN_SIGNAL_EXPIRED"
        return "OPEN"
    reason = trade.close_reason or "UNKNOWN"
    return f"CLOSED_{reason}"


class MonitoringService:
    """Vista unificada para supervisar trades del bot y salud del sistema."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()

    async def trade_journal(self, *, limit: int = 50) -> dict:
        user_trades = (
            await self.session.execute(
                select(UserTrade).order_by(desc(UserTrade.created_at)).limit(limit)
            )
        ).scalars().all()

        signal_ids = {t.signal_id for t in user_trades if t.signal_id}
        signals_map: dict[int, Signal] = {}
        if signal_ids:
            sigs = (
                await self.session.execute(select(Signal).where(Signal.id.in_(signal_ids)))
            ).scalars().all()
            signals_map = {s.id: s for s in sigs}

        entries = []
        open_auto = 0
        closed_auto = 0

        for t in user_trades:
            src = trade_source(t.notes)
            sig = signals_map.get(t.signal_id) if t.signal_id else None
            if src == "auto":
                if t.status == "OPEN":
                    open_auto += 1
                else:
                    closed_auto += 1

            broker_id = None
            if t.notes and "Binance" in t.notes:
                parts = t.notes.split("Binance")
                if len(parts) > 1:
                    broker_id = parts[-1].strip().split("|")[0].strip() or None

            entries.append(
                {
                    "id": t.id,
                    "signal_id": t.signal_id,
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "source": src,
                    "status": t.status,
                    "lifecycle": lifecycle_status(t, sig),
                    "close_reason": t.close_reason,
                    "close_reason_label": CLOSE_REASON_LABELS.get(
                        t.close_reason or "", t.close_reason or "—"
                    ),
                    "entry_price": str(t.entry_price),
                    "exit_price": str(t.exit_price) if t.exit_price else None,
                    "stop_loss": str(t.stop_loss),
                    "take_profit_1": str(t.take_profit_1) if t.take_profit_1 else None,
                    "take_profit_2": str(t.take_profit_2) if t.take_profit_2 else None,
                    "leverage": t.leverage,
                    "margin_used": str(t.margin_used),
                    "pnl_usdt": str(t.pnl_usdt) if t.pnl_usdt is not None else None,
                    "broker_order_id": broker_id,
                    "signal_status": sig.status if sig else None,
                    "signal_expires_at": sig.expires_at.isoformat() if sig and sig.expires_at else None,
                    "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                    "closed_at": t.closed_at.isoformat() if t.closed_at else None,
                    "notes": t.notes,
                }
            )

        paper = (
            await self.session.execute(
                select(PaperTrade).order_by(desc(PaperTrade.created_at)).limit(20)
            )
        ).scalars().all()

        return {
            "summary": {
                "total": len(entries),
                "open": sum(1 for e in entries if e["status"] == "OPEN"),
                "closed": sum(1 for e in entries if e["status"] == "CLOSED"),
                "auto_open": open_auto,
                "auto_closed": closed_auto,
                "paper_open": sum(1 for p in paper if p.status == "OPEN"),
            },
            "trades": entries,
            "paper_trades": [
                {
                    "id": p.id,
                    "symbol": p.symbol,
                    "direction": p.direction,
                    "status": p.status,
                    "source": "paper",
                    "close_reason": p.close_reason,
                    "close_reason_label": CLOSE_REASON_LABELS.get(
                        p.close_reason or "", p.close_reason or "—"
                    ),
                    "pnl_usdt": str(p.pnl_usdt) if p.pnl_usdt is not None else None,
                    "opened_at": p.opened_at.isoformat() if p.opened_at else None,
                    "closed_at": p.closed_at.isoformat() if p.closed_at else None,
                }
                for p in paper
            ],
        }

    async def recent_events(self, *, limit: int = 30) -> dict:
        total = (await self.session.execute(select(func.count()).select_from(AlertLog))).scalar() or 0
        delivered = (
            await self.session.execute(
                select(func.count()).select_from(AlertLog).where(AlertLog.delivered.is_(True))
            )
        ).scalar() or 0

        alerts = (
            await self.session.execute(
                select(AlertLog).order_by(desc(AlertLog.created_at)).limit(limit)
            )
        ).scalars().all()

        return {
            "alerts_total": total,
            "alerts_delivered": delivered,
            "alerts_failed": total - delivered,
            "recent": [
                {
                    "at": a.created_at.isoformat() if a.created_at else None,
                    "type": a.alert_type,
                    "signal_id": a.signal_id,
                    "delivered": a.delivered,
                }
                for a in alerts
            ],
        }

    async def _probe_ollama(self) -> tuple[bool, str | None, int | None]:
        ai = AIChartAnalyzer(self.settings)
        if not ai.is_available:
            return False, "IA desactivada", None
        started = datetime.now(UTC)
        try:
            import httpx

            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self.settings.ollama_base_url.rstrip('/')}/api/tags")
                if r.status_code != 200:
                    return False, f"HTTP {r.status_code}", None
        except Exception as exc:
            return False, str(exc), None
        ollama_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        return True, None, ollama_ms

    async def system_health(self, *, use_cache: bool = True) -> dict:
        global _health_cache
        if use_cache and _health_cache is not None:
            cached, cached_at = _health_cache
            if time.time() - cached_at < _HEALTH_CACHE_TTL_SECONDS:
                return cached

        monitor = get_monitor()
        monitor_status = monitor.status() if monitor else {"running": False}
        telegram = TelegramNotifier(self.settings)
        broker = BinanceBroker(self.settings)

        tg_check, ollama_probe, broker_snap = await asyncio.gather(
            telegram.check_connection(),
            self._probe_ollama(),
            asyncio.to_thread(broker.fetch_account, use_cache=True),
        )
        ollama_ok, ollama_error, ollama_ms = ollama_probe
        can_exec, exec_reason = broker.can_execute()
        trading_ok, trading_err = await asyncio.to_thread(broker.check_trading_permission)
        if can_exec and not trading_ok:
            can_exec = False
            exec_reason = trading_err

        warnings = []
        if not tg_check.get("ok"):
            warnings.append(f"Telegram: {tg_check.get('error')}")
        if self.settings.ai_gate_auto_trade and not ollama_ok:
            warnings.append(f"Ollama no responde: {ollama_error or 'offline'}")
        if self.settings.autonomous_trading_enabled and not trading_ok:
            warnings.append(f"Binance trading: {trading_err}")
        elif self.settings.autonomous_trading_enabled and not can_exec:
            warnings.append(f"Broker: {exec_reason}")

        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "monitor": monitor_status,
            "telegram": {
                "configured": telegram.is_configured,
                "ok": tg_check.get("ok"),
                "error": tg_check.get("error"),
            },
            "ollama": {
                "enabled": self.settings.ai_enabled,
                "model": self.settings.ollama_model,
                "ok": ollama_ok,
                "latency_ms": ollama_ms,
                "error": ollama_error,
            },
            "broker": {
                "connected": broker_snap.connected,
                "can_execute": can_exec,
                "reason": exec_reason,
                "trading_permission_ok": trading_ok,
                "positions": len(broker_snap.positions),
            },
            "autonomous": {
                "enabled": self.settings.autonomous_trading_enabled,
                "ai_gate": self.settings.ai_gate_auto_trade,
            },
            "warnings": warnings,
        }
        _health_cache = (payload, time.time())
        return payload
