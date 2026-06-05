from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.config.settings import get_settings
from trading_bot.db.models.signal import Signal
from trading_bot.db.session import get_db
from trading_bot.modules.ai_chart_analyzer.analyzer import AIChartAnalyzer
from trading_bot.modules.ai_chart_analyzer.behavior import SYSTEM_BEHAVIOR
from trading_bot.modules.ai_chart_analyzer.feedback import AIFeedbackStore

router = APIRouter(prefix="/ai", tags=["ai"])


class FeedbackRequest(BaseModel):
    signal_id: int | None = None
    symbol: str
    direction: str
    setup_grade: str
    ai_verdict: str
    ai_summary: str
    was_correct: bool
    user_notes: str | None = None


@router.get("/behavior")
async def get_ai_behavior() -> dict:
    settings = get_settings()
    return {
        "enabled": settings.ai_enabled,
        "model": settings.ollama_model,
        "vision_model": settings.ollama_vision_model,
        "max_confidence_adjustment": settings.ai_max_confidence_adjustment,
        "rules_summary": "La IA complementa, nunca decide sola. Máximo +5/-10 en confianza.",
        "system_prompt": SYSTEM_BEHAVIOR,
    }


@router.get("/status")
async def ai_status() -> dict:
    settings = get_settings()
    analyzer = AIChartAnalyzer(settings)
    return {
        "available": analyzer.is_available,
        "ollama_url": settings.ollama_base_url,
        "model": settings.ollama_model,
        "enabled": settings.ai_enabled,
    }


@router.post("/analyze/{signal_id}")
async def analyze_signal(signal_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    settings = get_settings()
    if not settings.ai_enabled:
        raise HTTPException(400, "IA desactivada. Activa AI_ENABLED=true en .env")

    result = await db.execute(select(Signal).where(Signal.id == signal_id))
    signal = result.scalar_one_or_none()
    if not signal or not signal.should_trade:
        raise HTTPException(404, "Señal no encontrada o no operable")

    store = AIFeedbackStore(db)
    few_shot = await store.get_few_shot_examples()
    analyzer = AIChartAnalyzer(settings)
    analysis = await analyzer.analyze_setup(
        symbol=signal.symbol,
        direction=signal.direction,
        setup_grade=signal.setup_grade,
        technical_explanation=signal.technical_explanation or "",
        entry=str(signal.entry_price) if signal.entry_price else None,
        stop=str(signal.stop_loss) if signal.stop_loss else None,
        tp2=str(signal.take_profit_2) if signal.take_profit_2 else None,
        few_shot_examples=few_shot,
    )

    adjusted = signal.confidence_score + analysis.confidence_delta
    adjusted = max(Decimal("0"), min(Decimal("100"), adjusted))

    return {
        "signal_id": signal_id,
        "original_confidence": str(signal.confidence_score),
        "adjusted_confidence": str(adjusted.quantize(Decimal("0.01"))),
        "verdict": analysis.verdict,
        "confidence_delta": str(analysis.confidence_delta),
        "summary": analysis.summary,
        "risks": analysis.risks,
        "invalidation_hint": analysis.invalidation_hint,
        "model_used": analysis.model_used,
        "available": analysis.available,
        "note": "Esto es complementario. La decisión final sigue siendo del sistema de riesgo.",
    }


@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest, db: AsyncSession = Depends(get_db)) -> dict:
    store = AIFeedbackStore(db)
    entry = await store.record(
        signal_id=body.signal_id,
        symbol=body.symbol,
        direction=body.direction,
        setup_grade=body.setup_grade,
        ai_verdict=body.ai_verdict,
        ai_summary=body.ai_summary,
        was_correct=body.was_correct,
        user_notes=body.user_notes,
    )
    await db.commit()
    stats = await store.stats()
    return {
        "ok": True,
        "feedback_id": entry.id,
        "training_stats": stats,
        "message": "Retroalimentación guardada. Se usará en futuros análisis (few-shot).",
    }


@router.get("/training-stats")
async def training_stats(db: AsyncSession = Depends(get_db)) -> dict:
    store = AIFeedbackStore(db)
    return await store.stats()
