from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import get_settings
from trading_bot.db.models.account import Account
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.db.session import get_db
from trading_bot.features.ai.analyzer import AIChartAnalyzer
from trading_bot.features.autonomous.service import AutonomousTraderService
from trading_bot.features.broker.binance_broker import BinanceBroker
from trading_bot.features.signals.monitor.price_feed import PriceFeed

router = APIRouter(prefix="/autonomous", tags=["autonomous"])


def _result_dict(result) -> dict:
    return {
        "executed": result.executed,
        "trade_id": result.trade_id,
        "broker_order_id": result.broker_order_id,
        "message": result.message,
        "ai_verdict": result.ai_verdict,
        "blocked_reason": result.blocked_reason,
    }


@router.get("/status")
async def autonomous_status() -> dict:
    settings = get_settings()
    broker = BinanceBroker()
    can_exec, exec_reason = broker.can_execute()
    ai = AIChartAnalyzer()

    return {
        "enabled": settings.autonomous_trading_enabled,
        "ai_gate": settings.ai_gate_auto_trade,
        "ai_required": settings.ai_required_for_auto_trade,
        "ai_min_verdict": settings.ai_auto_min_verdict,
        "ai_available": ai.is_available,
        "min_balance_usdt": settings.min_balance_for_autonomous,
        "compound_on_close": settings.compound_balance_on_close,
        "broker_can_execute": can_exec,
        "broker_reason": exec_reason,
        "endpoints": {
            "pending": "GET /api/v1/autonomous/pending — señales ACTIVE sin trade",
            "preview": "GET /api/v1/autonomous/preview/{signal_id} — qué dice la IA",
            "try_entry": "POST /api/v1/autonomous/try-entry/{signal_id} — forzar intento ahora",
        },
        "flow": [
            "1. Monitor detecta ENTRAR AHORA (precio toca entrada)",
            "2. IA (Ollama) evalúa el setup si AI_GATE_AUTO_TRADE=true",
            "3. Si IA ≥ CONFIRM → abre trade en DB + Binance (si broker activo)",
            "4. SL/TP en exchange + seguimiento local del P&L",
            "5. Telegram te avisa de cada acción",
        ],
        "warning": (
            "Ningún bot garantiza crecimiento de capital. Con ~2 USDT el mínimo de Binance "
            "bloqueará la mayoría de órdenes. Usa testnet o ≥10–20 USDT para probar en serio."
        ),
    }


@router.get("/pending")
async def pending_entries(db: AsyncSession = Depends(get_db)) -> dict:
    """Señales ACTIVE que aún no tienen trade (candidatas a reintento autónomo)."""
    settings = get_settings()
    active_types = settings.active_profile_type_set()

    signals = (
        await db.execute(
            select(Signal)
            .where(Signal.status == "ACTIVE", Signal.should_trade.is_(True))
            .order_by(desc(Signal.created_at))
            .limit(20)
        )
    ).scalars().all()

    pending = []
    for sig in signals:
        acc = (
            await db.execute(select(Account).where(Account.id == sig.account_id))
        ).scalar_one_or_none()
        if not acc or acc.profile_type not in active_types:
            continue
        has_trade = (
            await db.execute(select(UserTrade.id).where(UserTrade.signal_id == sig.id).limit(1))
        ).scalar_one_or_none()
        if has_trade:
            continue
        pending.append(
            {
                "signal_id": sig.id,
                "symbol": sig.symbol,
                "direction": sig.direction,
                "grade": sig.setup_grade,
                "entry": str(sig.entry_price),
                "profile": acc.name,
                "expires_at": sig.expires_at.isoformat() if sig.expires_at else None,
            }
        )

    return {
        "count": len(pending),
        "active_profile_types": sorted(active_types),
        "pending": pending,
        "hint": "Usa POST /try-entry/{signal_id} para forzar IA + ejecución ahora.",
    }


@router.get("/preview/{signal_id}")
async def preview_ai_verdict(signal_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Muestra qué veredicto daría Ollama sin ejecutar orden."""
    sig = (await db.execute(select(Signal).where(Signal.id == signal_id))).scalar_one_or_none()
    if not sig:
        raise HTTPException(404, "Señal no encontrada")

    feed = PriceFeed(use_live=get_settings().monitor_use_live_data)
    try:
        current_price = str(feed.get_price(sig.symbol))
    except Exception as exc:
        current_price = None
        price_error = str(exc)
    else:
        price_error = None

    preview = await AutonomousTraderService(db).preview_ai(sig)
    return {
        "signal_id": signal_id,
        "symbol": sig.symbol,
        "direction": sig.direction,
        "status": sig.status,
        "current_price": current_price,
        "price_error": price_error,
        "ai": preview,
    }


@router.post("/try-entry/{signal_id}")
async def try_entry_now(signal_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    """Fuerza evaluación IA + entrada autónoma para una señal (prueba manual)."""
    settings = get_settings()
    if not settings.autonomous_trading_enabled:
        raise HTTPException(400, "AUTONOMOUS_TRADING_ENABLED=false en .env")

    sig = (await db.execute(select(Signal).where(Signal.id == signal_id))).scalar_one_or_none()
    if not sig:
        raise HTTPException(404, "Señal no encontrada")
    if sig.status not in ("ACTIVE", "WATCHING"):
        raise HTTPException(400, f"Señal en estado {sig.status} — solo ACTIVE o WATCHING")

    acc = (await db.execute(select(Account).where(Account.id == sig.account_id))).scalar_one_or_none()
    if not acc or acc.profile_type not in settings.active_profile_type_set():
        raise HTTPException(400, f"Perfil {acc.profile_type if acc else '?'} no está en ACTIVE_PROFILE_TYPES")

    feed = PriceFeed(use_live=settings.monitor_use_live_data)
    try:
        price = feed.get_price(sig.symbol)
    except Exception as exc:
        raise HTTPException(502, f"No se pudo obtener precio: {exc}") from exc

    svc = AutonomousTraderService(db, get_settings())
    preview = await svc.preview_ai(sig) if settings.ai_gate_auto_trade else {"skipped": "AI_GATE_AUTO_TRADE=false"}
    result = await svc.process_entry(sig, Decimal(str(price)))
    await db.commit()
    await db.refresh(sig)

    return {
        "signal_id": signal_id,
        "symbol": sig.symbol,
        "current_price": str(price),
        "ai_preview": preview,
        "result": _result_dict(result),
    }
