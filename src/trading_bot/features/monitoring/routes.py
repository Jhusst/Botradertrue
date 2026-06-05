from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.db.session import get_db
from trading_bot.features.monitoring.service import MonitoringService

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/journal")
async def trade_journal(limit: int = 50, db: AsyncSession = Depends(get_db)) -> dict:
    """Historial de trades del bot: abiertos, cerrados por SL/TP/caducidad."""
    return await MonitoringService(db).trade_journal(limit=min(limit, 100))


@router.get("/events")
async def monitoring_events(db: AsyncSession = Depends(get_db)) -> dict:
    """Alertas recientes y tasa de entrega Telegram."""
    return await MonitoringService(db).recent_events()


@router.get("/health")
async def monitoring_health(db: AsyncSession = Depends(get_db)) -> dict:
    """Salud: monitor, Ollama, Telegram, Binance y avisos."""
    return await MonitoringService(db).system_health()


@router.get("/overview")
async def monitoring_overview(db: AsyncSession = Depends(get_db)) -> dict:
    """Resumen completo para supervisión."""
    svc = MonitoringService(db)
    journal = await svc.trade_journal(limit=30)
    events = await svc.recent_events(limit=15)
    health = await svc.system_health()
    return {
        "health": health,
        "summary": journal["summary"],
        "open_bot_trades": [t for t in journal["trades"] if t["source"] == "auto" and t["status"] == "OPEN"],
        "recent_closed": [
            t for t in journal["trades"] if t["status"] == "CLOSED"
        ][:10],
        "recent_alerts": events["recent"][:10],
        "warnings": health["warnings"],
    }
