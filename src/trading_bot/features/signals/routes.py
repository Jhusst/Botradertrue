from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import get_settings
from trading_bot.core.enums import SignalStatus
from trading_bot.db.models.signal import Signal
from trading_bot.db.session import get_db
from trading_bot.infrastructure.market_data.ccxt_client import DataCollector
from trading_bot.features.signals.generator import SignalGenerator
from trading_bot.features.signals.outcome_tracker import SignalOutcomeTracker
from trading_bot.features.signals.strategies.trend_pullback_mvp import MarketContext
from trading_bot.features.alerts.telegram import TelegramNotifier
from trading_bot.schemas.risk import AccountRiskState
from trading_bot.schemas.signal import SignalCreate, SignalListResponse, SignalResponse

router = APIRouter(prefix="/signals", tags=["signals"])


def _signal_to_model(data: SignalCreate, account_id: int | None = None) -> Signal:
    return Signal(
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
        should_trade=data.should_trade,
        rejection_reason=data.rejection_reason,
        strategy_name=data.strategy_name,
    )


@router.get("", response_model=SignalListResponse)
async def list_signals(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    symbol: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> SignalListResponse:
    query = select(Signal).order_by(Signal.created_at.desc())
    count_query = select(func.count()).select_from(Signal)

    if symbol:
        query = query.where(Signal.symbol == symbol)
        count_query = count_query.where(Signal.symbol == symbol)

    total = (await db.execute(count_query)).scalar() or 0
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    items = result.scalars().all()

    return SignalListResponse(
        items=[SignalResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{signal_id}", response_model=SignalResponse)
async def get_signal(signal_id: int, db: AsyncSession = Depends(get_db)) -> SignalResponse:
    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal:
        raise HTTPException(status_code=404, detail="Señal no encontrada")
    return SignalResponse.model_validate(signal)


@router.post("/generate", response_model=SignalResponse)
async def generate_signal(
    symbol: str = "BTC/USDT",
    balance: Decimal = Decimal("10000"),
    use_live_data: bool = False,
    notify_telegram: bool = True,
    db: AsyncSession = Depends(get_db),
) -> SignalResponse:
    collector = DataCollector()
    if use_live_data:
        try:
            data = collector.fetch_multi_timeframe(symbol)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Error obteniendo datos: {exc}") from exc
    else:
        data = collector.generate_sample_data()

    generator = SignalGenerator()
    account = AccountRiskState(balance_usdt=balance)
    ctx = MarketContext(
        symbol=symbol,
        df_4h=data["4h"],
        df_1h=data["1h"],
        df_15m=data["15m"],
    )
    signal_data = generator.generate(ctx, account)
    signal_data.symbol = symbol

    db_signal = _signal_to_model(signal_data)
    if signal_data.should_trade:
        settings = get_settings()
        db_signal.status = SignalStatus.WATCHING.value
        db_signal.expires_at = datetime.now(UTC) + timedelta(hours=settings.signal_ttl_hours)
    db.add(db_signal)
    await db.flush()
    if signal_data.should_trade:
        await SignalOutcomeTracker(db).register_new_signal(db_signal)
    await db.commit()
    await db.refresh(db_signal)

    if notify_telegram:
        notifier = TelegramNotifier()
        response = SignalResponse.model_validate(db_signal)
        await notifier.send_signal(response, urgent=signal_data.should_trade)

    return SignalResponse.model_validate(db_signal)
