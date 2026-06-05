from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.core.profile_presets import PRESETS
from trading_bot.db.models.account import Account
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.db.session import get_db

router = APIRouter(prefix="/profiles", tags=["profiles"])


class BalanceUpdate(BaseModel):
    balance_usdt: Decimal = Field(gt=0, decimal_places=8)


def _profile_dict(account: Account, open_trades: int, realized_pnl: Decimal) -> dict:
    preset = PRESETS.get(account.profile_type)
    equity = account.balance_usdt + realized_pnl
    return {
        "id": account.id,
        "name": account.name,
        "profile_type": account.profile_type,
        "description": preset.description if preset else "",
        "balance_usdt": str(account.balance_usdt),
        "initial_balance_usdt": str(account.initial_balance_usdt),
        "equity_usdt": str(equity.quantize(Decimal("0.01"))),
        "realized_pnl_usdt": str(realized_pnl.quantize(Decimal("0.01"))),
        "risk_setup_a": str(account.risk_setup_a),
        "risk_setup_b": str(account.risk_setup_b),
        "max_leverage": account.max_leverage,
        "min_setup_grade": account.min_setup_grade,
        "open_trades": open_trades,
        "consecutive_losses": account.consecutive_losses,
    }


@router.get("")
async def list_profiles(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(Account).order_by(Account.id))
    accounts = result.scalars().all()
    profiles = []
    total_equity = Decimal("0")
    total_realized = Decimal("0")

    for acc in accounts:
        trades = await db.execute(
            select(UserTrade).where(UserTrade.account_id == acc.id)
        )
        user_trades = trades.scalars().all()
        open_count = sum(1 for t in user_trades if t.status == "OPEN")
        realized = sum((t.pnl_usdt or Decimal("0")) for t in user_trades if t.status == "CLOSED")
        total_realized += realized
        total_equity += acc.balance_usdt + realized
        profiles.append(_profile_dict(acc, open_count, realized))

    return {
        "profiles": profiles,
        "portfolio": {
            "total_equity_usdt": str(total_equity.quantize(Decimal("0.01"))),
            "total_realized_pnl_usdt": str(total_realized.quantize(Decimal("0.01"))),
        },
    }


@router.put("/{profile_id}/balance")
async def update_balance(
    profile_id: int, body: BalanceUpdate, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await db.execute(select(Account).where(Account.id == profile_id))
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(404, "Perfil no encontrado")
    account.balance_usdt = body.balance_usdt
    await db.commit()
    await db.refresh(account)
    return {"ok": True, "balance_usdt": str(account.balance_usdt)}
