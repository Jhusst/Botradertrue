import pytest

from trading_bot.modules.ai_chart_analyzer.analyzer import AIChartAnalyzer
from trading_bot.modules.ai_chart_analyzer.behavior import SYSTEM_BEHAVIOR, build_analysis_prompt


def test_behavior_prompt_has_rules() -> None:
    assert "NUNCA" in SYSTEM_BEHAVIOR
    assert "CONFIRM" in SYSTEM_BEHAVIOR


def test_build_analysis_prompt() -> None:
    prompt = build_analysis_prompt(
        symbol="XAU/USDT:USDT",
        direction="LONG",
        setup_grade="A",
        technical_explanation="Tendencia alcista en 4H.",
        entry="4320.00",
        stop="4300.00",
        tp2="4360.00",
        few_shot_examples=["Oro LONG grado A: IA dijo CONFIRM — CORRECTO."],
    )
    assert "XAU/USDT:USDT" in prompt
    assert "Ejemplos previos" in prompt


@pytest.mark.asyncio
async def test_analyzer_disabled_returns_neutral() -> None:
    from trading_bot.config.settings import Settings

    settings = Settings(ai_enabled=False)
    analyzer = AIChartAnalyzer(settings)
    result = await analyzer.analyze_setup(
        symbol="BTC/USDT",
        direction="LONG",
        setup_grade="A",
        technical_explanation="Test",
    )
    assert result.verdict == "NEUTRAL"
    assert result.available is False
