from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.db.models.trade import PaperTrade
from trading_bot.db.session import get_db
from trading_bot.features.trades.paper.simulator import PaperTradingSimulator

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])


@router.get("")
async def list_paper_trades(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(PaperTrade).order_by(PaperTrade.created_at.desc()).limit(50))
    trades = result.scalars().all()
    return {
        "items": [
            {
                "id": t.id,
                "signal_id": t.signal_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "status": t.status,
                "entry_price": str(t.entry_price),
                "pnl_usdt": str(t.pnl_usdt) if t.pnl_usdt else None,
                "close_reason": t.close_reason,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in trades
        ],
        "stats": PaperTradingSimulator().get_stats(),
    }
