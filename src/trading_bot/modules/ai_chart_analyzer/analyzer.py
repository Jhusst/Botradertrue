import json
import re
from dataclasses import dataclass
from decimal import Decimal

import httpx

from trading_bot.config.settings import Settings, get_settings
from trading_bot.modules.ai_chart_analyzer.behavior import SYSTEM_BEHAVIOR, build_analysis_prompt


@dataclass
class AIAnalysisResult:
    verdict: str
    confidence_delta: Decimal
    summary: str
    risks: list[str]
    invalidation_hint: str
    raw_response: str
    model_used: str
    available: bool


class AIChartAnalyzer:
    """Analizador complementario vía Ollama. Nunca aprueba trades por sí solo."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def is_available(self) -> bool:
        return self.settings.ai_enabled and bool(self.settings.ollama_base_url)

    async def analyze_setup(
        self,
        symbol: str,
        direction: str,
        setup_grade: str,
        technical_explanation: str,
        entry: str | None = None,
        stop: str | None = None,
        tp2: str | None = None,
        few_shot_examples: list[str] | None = None,
    ) -> AIAnalysisResult:
        if not self.is_available:
            return AIAnalysisResult(
                verdict="NEUTRAL",
                confidence_delta=Decimal("0"),
                summary="IA desactivada o Ollama no configurado.",
                risks=[],
                invalidation_hint="N/A",
                raw_response="",
                model_used="",
                available=False,
            )

        prompt = build_analysis_prompt(
            symbol=symbol,
            direction=direction,
            setup_grade=setup_grade,
            technical_explanation=technical_explanation,
            entry=entry,
            stop=stop,
            tp2=tp2,
            few_shot_examples=few_shot_examples,
        )

        try:
            raw = await self._call_ollama(prompt)
            parsed = self._parse_response(raw)
            max_adj = Decimal(str(self.settings.ai_max_confidence_adjustment))
            raw_delta = Decimal(str(parsed["confidence_delta"]))
            delta = max(Decimal("-10"), min(Decimal("5"), raw_delta))
            delta = max(-max_adj, min(max_adj, delta))
            return AIAnalysisResult(
                verdict=parsed["verdict"],
                confidence_delta=delta,
                summary=parsed["summary"],
                risks=parsed.get("risks", []),
                invalidation_hint=parsed.get("invalidation_hint", ""),
                raw_response=raw,
                model_used=self.settings.ollama_model,
                available=True,
            )
        except Exception as exc:
            return AIAnalysisResult(
                verdict="NEUTRAL",
                confidence_delta=Decimal("0"),
                summary=f"Error de IA: {exc}",
                risks=[],
                invalidation_hint="N/A",
                raw_response=str(exc),
                model_used=self.settings.ollama_model,
                available=False,
            )

    async def _call_ollama(self, prompt: str) -> str:
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.settings.ollama_model,
            "messages": [
                {"role": "system", "content": SYSTEM_BEHAVIOR},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")

    @staticmethod
    def _parse_response(raw: str) -> dict:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {
                "verdict": "NEUTRAL",
                "confidence_delta": 0,
                "summary": raw[:200],
                "risks": [],
                "invalidation_hint": "",
            }
