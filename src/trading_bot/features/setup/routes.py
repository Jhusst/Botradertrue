from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import get_settings
from trading_bot.db.models.alert_log import AlertLog
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.db.session import get_db
from trading_bot.features.alerts.telegram import TelegramNotifier

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/check")
async def setup_check() -> dict:
    """Diagnóstico: qué está configurado y qué falta."""
    settings = get_settings()
    notifier = TelegramNotifier(settings)

    telegram_token = bool(settings.telegram_bot_token.strip())
    telegram_chat = bool(settings.telegram_chat_id.strip())
    telegram_ok = notifier.is_configured

    missing: list[dict] = []

    if not telegram_token:
        missing.append({
            "component": "telegram",
            "field": "TELEGRAM_BOT_TOKEN",
            "severity": "required",
            "reason": "Sin token el bot no puede enviar mensajes a Telegram.",
            "how_to_fix": "Crea un bot con @BotFather en Telegram y copia el token al archivo .env",
        })
    if not telegram_chat:
        missing.append({
            "component": "telegram",
            "field": "TELEGRAM_CHAT_ID",
            "severity": "required",
            "reason": "Sin chat_id el bot no sabe a quién enviar las alertas.",
            "how_to_fix": "Obtén tu ID con @userinfobot o @getidsbot y ponlo en .env",
        })

    if not settings.monitor_use_live_data:
        missing.append({
            "component": "market_data",
            "field": "MONITOR_USE_LIVE_DATA",
            "severity": "warning",
            "reason": "Con datos sintéticos las señales no reflejan el mercado real.",
            "how_to_fix": "Pon MONITOR_USE_LIVE_DATA=true en .env (no requiere API keys de Binance)",
        })

    return {
        "ready_for_alerts": telegram_ok and settings.monitor_enabled,
        "ready_for_live_signals": settings.monitor_use_live_data,
        "telegram": {
            "configured": telegram_ok,
            "bot_token_set": telegram_token,
            "chat_id_set": telegram_chat,
            "explanation": (
                "Telegram es el canal de alertas al móvil. "
                "El sistema NO puede conectarse solo: tú debes crear el bot y poner token + chat_id en .env. "
                "No es un error del código — son credenciales que solo tú puedes generar."
            ),
        },
        "exchange": {
            "needs_api_keys_for_data": False,
            "explanation": (
                "Precios y velas: API pública de Binance (sin keys). "
                "Cuenta y órdenes: BINANCE_API_KEY + SECRET con permiso solo trading (sin retiros). "
                "Bitunix no tiene conector CCXT — usa Binance Futures para auto-ejecución."
            ),
            "api_key_set": bool(settings.binance_api_key),
            "broker_enabled": settings.broker_enabled,
            "auto_execute_on_enter": settings.auto_execute_on_enter,
            "live_mode_enabled": settings.live_mode_enabled,
            "testnet": settings.binance_testnet,
        },
        "monitor": {
            "enabled": settings.monitor_enabled,
            "symbols": [s.strip() for s in settings.watch_symbols.split(",") if s.strip()],
            "scan_interval_seconds": settings.scan_interval_seconds,
            "price_check_interval_seconds": settings.price_check_interval_seconds,
        },
        "missing": missing,
        "steps": [
            "1. Abre Telegram → busca @BotFather → /newbot → copia el token",
            "2. Busca @userinfobot → Start → copia tu Id (chat_id)",
            "3. Edita .env: TELEGRAM_BOT_TOKEN=... y TELEGRAM_CHAT_ID=...",
            "4. Reinicia la API: ./scripts/run_api.sh",
            "5. Prueba: curl -X POST http://localhost:8000/api/v1/setup/test-telegram",
        ],
    }


@router.post("/test-telegram")
async def test_telegram() -> dict:
    """Envía un mensaje de prueba a tu Telegram."""
    notifier = TelegramNotifier(get_settings())
    result = await notifier.probe()
    if not notifier.is_configured:
        result["help_url"] = "/docs/TELEGRAM_SETUP.md"
        result["detail"] = "Faltan TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID en .env"
    elif not result["ok"]:
        result["hint"] = (
            "Si dice 'chat not found': abre tu bot en Telegram y pulsa Start (/start), "
            "luego verifica TELEGRAM_CHAT_ID con @userinfobot."
        )
    else:
        result["message"] = "Mensaje enviado a Telegram"
    return result


@router.get("/activity")
async def bot_activity(db: AsyncSession = Depends(get_db)) -> dict:
    """Últimas alertas, entregas Telegram e intentos de trade — para depurar."""
    settings = get_settings()
    total_alerts = (await db.execute(select(func.count()).select_from(AlertLog))).scalar() or 0
    delivered = (
        await db.execute(select(func.count()).select_from(AlertLog).where(AlertLog.delivered.is_(True)))
    ).scalar() or 0

    recent_alerts = (
        await db.execute(select(AlertLog).order_by(desc(AlertLog.created_at)).limit(20))
    ).scalars().all()

    open_trades = (
        await db.execute(select(UserTrade).where(UserTrade.status == "OPEN").order_by(desc(UserTrade.created_at)))
    ).scalars().all()

    active_signals = (
        await db.execute(
            select(Signal).where(Signal.status == "ACTIVE").order_by(desc(Signal.created_at)).limit(10)
        )
    ).scalars().all()

    telegram_status = await TelegramNotifier(settings).check_connection()

    return {
        "telegram": {
            "configured": TelegramNotifier(settings).is_configured,
            "connection_ok": telegram_status.get("ok"),
            "connection_error": telegram_status.get("error"),
        },
        "autonomous": {
            "enabled": settings.autonomous_trading_enabled,
            "broker_enabled": settings.broker_enabled,
            "live_mode_enabled": settings.live_mode_enabled,
        },
        "alerts": {
            "total": total_alerts,
            "delivered": delivered,
            "failed": total_alerts - delivered,
            "recent": [
                {
                    "at": a.created_at.isoformat() if a.created_at else None,
                    "type": a.alert_type,
                    "signal_id": a.signal_id,
                    "delivered": a.delivered,
                }
                for a in recent_alerts
            ],
        },
        "open_trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "direction": t.direction,
                "notes": t.notes,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            }
            for t in open_trades
        ],
        "active_signals_count": len(active_signals),
        "active_signals": [
            {"id": s.id, "symbol": s.symbol, "direction": s.direction, "entry": str(s.entry_price)}
            for s in active_signals
        ],
    }
