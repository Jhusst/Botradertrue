from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.db.models.signal import Signal
from trading_bot.db.models.signal_outcome import SignalOutcome
from trading_bot.db.session import get_db
from trading_bot.features.signals.outcome_tracker import OUTCOME_LABELS, RESOLVED_OUTCOMES

router = APIRouter(prefix="/signal-outcomes", tags=["signals"])


@router.get("")
async def signal_outcomes_history(
    limit: int = Query(50, ge=1, le=200),
    executed_only: bool | None = Query(None, description="true=solo ejecutadas, false=solo no ejecutadas"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Histórico de señales con resultado hipotético (TP/SL) para medir efectividad."""
    query = (
        select(SignalOutcome, Signal)
        .join(Signal, Signal.id == SignalOutcome.signal_id)
        .order_by(desc(SignalOutcome.created_at))
        .limit(limit)
    )
    if executed_only is True:
        query = query.where(SignalOutcome.executed.is_(True))
    elif executed_only is False:
        query = query.where(SignalOutcome.executed.is_(False))

    rows = (await db.execute(query)).all()

    entries = []
    wins = 0
    losses = 0
    pending = 0
    not_executed = 0

    for outcome, signal in rows:
        if not outcome.executed:
            not_executed += 1
        if outcome.outcome in ("TP1", "TP2"):
            wins += 1
        elif outcome.outcome in ("STOP_LOSS", "INVALIDATED"):
            losses += 1
        elif outcome.outcome == "PENDING":
            pending += 1

        entries.append(
            {
                "signal_id": signal.id,
                "symbol": signal.symbol,
                "direction": signal.direction,
                "grade": signal.setup_grade,
                "status": signal.status,
                "executed": outcome.executed,
                "skip_reason": outcome.skip_reason,
                "entry_touched": outcome.entry_touched,
                "outcome": outcome.outcome,
                "outcome_label": outcome.outcome_label or OUTCOME_LABELS.get(outcome.outcome, outcome.outcome),
                "entry_price": str(signal.entry_price) if signal.entry_price else None,
                "stop_loss": str(signal.stop_loss) if signal.stop_loss else None,
                "take_profit_1": str(signal.take_profit_1) if signal.take_profit_1 else None,
                "take_profit_2": str(signal.take_profit_2) if signal.take_profit_2 else None,
                "exit_price": str(outcome.exit_price) if outcome.exit_price else None,
                "created_at": signal.created_at.isoformat() if signal.created_at else None,
                "resolved_at": outcome.resolved_at.isoformat() if outcome.resolved_at else None,
            }
        )

    resolved = wins + losses
    effectiveness = round(wins / resolved * 100, 1) if resolved else None

    total_q = await db.execute(select(func.count()).select_from(SignalOutcome))
    total = total_q.scalar() or 0

    return {
        "summary": {
            "total_tracked": total,
            "in_page": len(entries),
            "not_executed": not_executed,
            "wins_tp": wins,
            "losses_sl": losses,
            "pending": pending,
            "effectiveness_pct": effectiveness,
            "note": "Toda señal operable se registra al crearse. Al caducar se mide si el precio tocó TP/SL (min/max), ejecutada o no.",
        },
        "outcomes": entries,
    }
