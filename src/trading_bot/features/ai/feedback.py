from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trading_bot.db.models.ai_feedback import AIFeedback


class AIFeedbackStore:
    """Almacena retroalimentación para mejorar prompts (few-shot learning)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        symbol: str,
        direction: str,
        setup_grade: str,
        ai_verdict: str,
        ai_summary: str,
        was_correct: bool | None,
        user_notes: str | None = None,
        signal_id: int | None = None,
    ) -> AIFeedback:
        entry = AIFeedback(
            signal_id=signal_id,
            symbol=symbol,
            direction=direction,
            setup_grade=setup_grade,
            ai_verdict=ai_verdict,
            ai_summary=ai_summary,
            was_correct=was_correct,
            user_notes=user_notes,
        )
        self.session.add(entry)
        await self.session.flush()
        return entry

    async def get_few_shot_examples(self, limit: int = 5) -> list[str]:
        result = await self.session.execute(
            select(AIFeedback)
            .where(AIFeedback.was_correct.isnot(None))
            .order_by(AIFeedback.created_at.desc())
            .limit(limit * 3)
        )
        rows = result.scalars().all()
        examples: list[str] = []
        for row in rows:
            if row.was_correct is True:
                examples.append(
                    f"{row.symbol} {row.direction} grado {row.setup_grade}: "
                    f"IA dijo {row.ai_verdict} — CORRECTO. {row.ai_summary}"
                )
            elif row.was_correct is False:
                examples.append(
                    f"{row.symbol} {row.direction} grado {row.setup_grade}: "
                    f"IA dijo {row.ai_verdict} — INCORRECTO. {row.ai_summary}"
                )
            if len(examples) >= limit:
                break
        return examples

    async def stats(self) -> dict:
        result = await self.session.execute(select(AIFeedback))
        rows = result.scalars().all()
        rated = [r for r in rows if r.was_correct is not None]
        correct = [r for r in rated if r.was_correct]
        return {
            "total": len(rows),
            "rated": len(rated),
            "correct": len(correct),
            "accuracy": round(len(correct) / len(rated), 4) if rated else None,
        }
