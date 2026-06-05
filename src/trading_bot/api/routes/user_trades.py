from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import get_settings
from trading_bot.db.models.account import Account
from trading_bot.db.models.signal import Signal
from trading_bot.db.models.user_trade import UserTrade
from trading_bot.db.session import get_db
from trading_bot.modules.execution_engine.binance_broker import BrokerOrderResult
from trading_bot.modules.execution_engine.engine import ExecutionEngine

router = APIRouter(prefix="/user-trades", tags=["user-trades"])


class EnterTradeRequest(BaseModel):
    signal_id: int
    profile_id: int
    leverage: int | None = None
    margin_used: Decimal | None = None
    notes: str | None = None
    manual_only: bool = True
    execute_on_broker: bool = False


class CloseTradeRequest(BaseModel):
    exit_price: Decimal | None = None
    pnl_usdt: Decimal | None = None
    close_reason: str = "MANUAL"


@router.get("")
async def list_user_trades(db: AsyncSession = Depends(get_db)) -> dict:
    result = await db.execute(select(UserTrade).order_by(UserTrade.created_at.desc()).limit(50))
    trades = result.scalars().all()
    return {
        "items": [
            {
                "id": t.id,
                "account_id": t.account_id,
                "signal_id": t.signal_id,
                "symbol": t.symbol,
                "direction": t.direction,
                "status": t.status,
                "entry_price": str(t.entry_price),
                "stop_loss": str(t.stop_loss),
                "take_profit_1": str(t.take_profit_1) if t.take_profit_1 else None,
                "take_profit_2": str(t.take_profit_2) if t.take_profit_2 else None,
                "margin_used": str(t.margin_used),
                "leverage": t.leverage,
                "risk_usdt": str(t.risk_usdt),
                "exit_price": str(t.exit_price) if t.exit_price else None,
                "pnl_usdt": str(t.pnl_usdt) if t.pnl_usdt else None,
                "close_reason": t.close_reason,
                "notes": t.notes,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                "closed_at": t.closed_at.isoformat() if t.closed_at else None,
            }
            for t in trades
        ]
    }


def _resolve_leverage(signal: Signal, account: Account, requested: int | None) -> int:
    lev = requested or signal.recommended_leverage or 1
    return min(max(int(lev), 1), account.max_leverage)


def _margin_for_leverage(signal: Signal, leverage: int) -> Decimal:
    if signal.position_size and leverage > 0:
        return (signal.position_size / Decimal(leverage)).quantize(Decimal("0.01"))
    if signal.margin_required and signal.recommended_leverage and leverage > 0:
        scaled = signal.margin_required * Decimal(signal.recommended_leverage) / Decimal(leverage)
        return scaled.quantize(Decimal("0.01"))
    return signal.margin_required or Decimal("0")


def _is_manual_trade(trade: UserTrade) -> bool:
    return (trade.notes or "").startswith("manual|")


@router.post("/enter")
async def enter_trade(body: EnterTradeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    sig_result = await db.execute(select(Signal).where(Signal.id == body.signal_id))
    signal = sig_result.scalar_one_or_none()
    if not signal or not signal.should_trade:
        raise HTTPException(400, "Señal no válida o no operable")

    acc_result = await db.execute(select(Account).where(Account.id == body.profile_id))
    account = acc_result.scalar_one_or_none()
    if not account:
        raise HTTPException(404, "Perfil no encontrado")

    open_trades = await db.execute(
        select(UserTrade).where(
            UserTrade.signal_id == body.signal_id,
            UserTrade.account_id == body.profile_id,
            UserTrade.status == "OPEN",
        )
    )
    for existing in open_trades.scalars().all():
        if _is_manual_trade(existing):
            raise HTTPException(400, "Ya tienes un trade manual abierto en esta señal")

    leverage = _resolve_leverage(signal, account, body.leverage)
    margin = body.margin_used or _margin_for_leverage(signal, leverage)
    manual_note = f"manual|lev={leverage}x|bitunix"
    trade = UserTrade(
        account_id=body.profile_id,
        signal_id=body.signal_id,
        symbol=signal.symbol,
        direction=signal.direction,
        status="OPEN",
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        take_profit_1=signal.take_profit_1,
        take_profit_2=signal.take_profit_2,
        margin_used=margin,
        leverage=leverage,
        risk_usdt=signal.risk_usdt or Decimal("0"),
        notes=body.notes or manual_note,
    )
    db.add(trade)
    signal.status = "ACTIVE"
    await db.commit()
    await db.refresh(trade)

    broker_result: BrokerOrderResult | None = None
    settings = get_settings()
    should_broker = (
        body.execute_on_broker
        and not body.manual_only
        and settings.broker_enabled
        and (settings.auto_execute_on_enter or settings.autonomous_trading_enabled)
    )
    if should_broker:
        engine = ExecutionEngine()
        position_usdt = signal.position_size or (margin * Decimal(str(trade.leverage)))
        try:
            broker_result = engine.execute(
                symbol=signal.symbol,
                direction=signal.direction,
                entry_price=signal.entry_price,
                position_size_usdt=position_usdt,
                leverage=trade.leverage,
                stop_loss=signal.stop_loss,
                take_profit_1=signal.take_profit_1,
            )
            if broker_result.ok and broker_result.order_id:
                trade.notes = (trade.notes or "") + f" | Binance order {broker_result.order_id}"
                await db.commit()
        except Exception as exc:
            broker_result = BrokerOrderResult(ok=False, message=str(exc))

    msg = f"Trade manual registrado ({leverage}x). Opera en Bitunix con esos niveles."
    if broker_result and broker_result.ok:
        msg = f"Trade registrado y ejecutado en Binance (orden {broker_result.order_id})."
    elif broker_result and not broker_result.ok:
        msg = f"Trade en DB. Binance: {broker_result.message}"

    return {
        "ok": True,
        "trade_id": trade.id,
        "message": msg,
        "leverage": leverage,
        "margin_used": str(margin),
        "broker": {
            "executed": bool(broker_result and broker_result.ok),
            "order_id": getattr(broker_result, "order_id", None),
            "detail": getattr(broker_result, "message", None),
        },
    }


@router.post("/{trade_id}/close")
async def close_trade(
    trade_id: int, body: CloseTradeRequest, db: AsyncSession = Depends(get_db)
) -> dict:
    result = await db.execute(select(UserTrade).where(UserTrade.id == trade_id))
    trade = result.scalar_one_or_none()
    if not trade or trade.status != "OPEN":
        raise HTTPException(404, "Trade abierto no encontrado")

    pnl = body.pnl_usdt
    if pnl is None and body.exit_price:
        diff = body.exit_price - trade.entry_price
        if trade.direction == "SHORT":
            diff = -diff
        pnl = (trade.margin_used * trade.leverage * diff / trade.entry_price).quantize(Decimal("0.01"))

    if pnl is None:
        raise HTTPException(400, "Indica pnl_usdt o exit_price")

    trade.status = "CLOSED"
    trade.exit_price = body.exit_price
    trade.pnl_usdt = pnl
    trade.close_reason = body.close_reason
    trade.closed_at = datetime.now(UTC)

    acc_result = await db.execute(select(Account).where(Account.id == trade.account_id))
    account = acc_result.scalar_one()
    account.balance_usdt += pnl
    account.daily_pnl_usdt += pnl
    account.weekly_pnl_usdt += pnl
    if pnl < 0:
        account.consecutive_losses += 1
    else:
        account.consecutive_losses = 0

    await db.commit()
    return {
        "ok": True,
        "pnl_usdt": str(pnl),
        "new_balance": str(account.balance_usdt),
    }
