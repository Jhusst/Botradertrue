from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import get_settings
from trading_bot.db.models.account import Account
from trading_bot.db.session import get_db
from trading_bot.modules.execution_engine.binance_broker import BinanceBroker

router = APIRouter(prefix="/broker", tags=["broker"])


class SyncBalanceRequest(BaseModel):
    profile_id: int


@router.get("/status")
async def broker_status() -> dict:
    settings = get_settings()
    broker = BinanceBroker()
    can, reason = broker.can_execute()
    account = broker.fetch_account()
    return {
        "broker_enabled": settings.broker_enabled,
        "auto_execute_on_enter": settings.auto_execute_on_enter,
        "live_mode_enabled": settings.live_mode_enabled,
        "testnet": settings.binance_testnet,
        "api_configured": broker.is_configured(),
        "can_execute": can,
        "execute_reason": reason,
        "account": {
            "connected": account.connected,
            "exchange": account.exchange,
            "usdt_balance": account.usdt_balance,
            "available_balance": account.available_balance,
            "positions": account.positions,
            "message": account.message,
        },
        "note": (
            "Bitunix no tiene API en CCXT. Para auto-ejecución usa Binance Futures "
            "con API key (solo trading, sin retiros). Prueba testnet primero."
        ),
    }


@router.post("/sync-balance")
async def sync_balance_from_broker(
    body: SyncBalanceRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    settings = get_settings()
    if not settings.sync_balance_from_broker:
        raise HTTPException(400, "Activa SYNC_BALANCE_FROM_BROKER=true en .env")

    broker = BinanceBroker()
    if not broker.is_configured():
        raise HTTPException(400, "Configura BINANCE_API_KEY y BINANCE_API_SECRET")

    account_snap = broker.fetch_account()
    if not account_snap.connected or not account_snap.available_balance:
        raise HTTPException(502, account_snap.message or "No se pudo leer balance")

    result = await db.execute(select(Account).where(Account.id == body.profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(404, "Perfil no encontrado")

    from decimal import Decimal

    profile.balance_usdt = Decimal(account_snap.available_balance)
    await db.commit()
    return {
        "ok": True,
        "profile_id": profile.id,
        "balance_usdt": str(profile.balance_usdt),
        "source": "binance",
    }
