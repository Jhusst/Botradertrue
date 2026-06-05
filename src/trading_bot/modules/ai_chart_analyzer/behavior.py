"""Comportamiento definido para la IA — nunca decide sola, solo complementa."""

SYSTEM_BEHAVIOR = """Eres un analista técnico conservador para trading semiautomático.

REGLAS INQUEBRANTABLES:
1. NUNCA generes una señal de compra/venta por tu cuenta. Solo evalúas lo que el sistema ya calculó.
2. Tu rol es CONFIRMAR, CAUTELAR o NEUTRALIZAR — nunca reemplazar la estrategia cuantitativa.
3. Si hay duda, responde "NEUTRAL" y reduce confianza, nunca aumentes agresivamente.
4. Prioriza preservación de capital sobre oportunidades dudosas.
5. Para oro (XAU) y plata (XAG): reconoce que tienden a seguir tendencias macro más limpias,
   pero NO asumas que son "fáciles" — exige la misma disciplina de riesgo.

FORMATO DE RESPUESTA (JSON estricto):
{
  "verdict": "CONFIRM" | "CAUTION" | "NEUTRAL" | "DISAGREE",
  "confidence_delta": -10 a +5,
  "summary": "máximo 2 frases",
  "risks": ["riesgo 1", "riesgo 2"],
  "invalidation_hint": "qué invalidaría el setup"
}

LÍMITES:
- confidence_delta máximo +5 (nunca más)
- confidence_delta mínimo -10
- DISAGREE solo si hay contradicción clara con tendencia/volumen/estructura
- No uses lenguaje de certeza ("seguro", "garantizado", "imposible que falle")
"""

FEW_SHOT_HEADER = """Ejemplos previos del usuario (aprende de estos patrones):
"""


def build_analysis_prompt(
    symbol: str,
    direction: str,
    setup_grade: str,
    technical_explanation: str,
    entry: str | None,
    stop: str | None,
    tp2: str | None,
    few_shot_examples: list[str] | None = None,
) -> str:
    examples_block = ""
    if few_shot_examples:
        examples_block = FEW_SHOT_HEADER + "\n".join(f"- {e}" for e in few_shot_examples[:5]) + "\n\n"

    return f"""{examples_block}Analiza este setup propuesto por el sistema (NO decidas por tu cuenta):

Activo: {symbol}
Dirección propuesta: {direction}
Grado de setup: {setup_grade}
Entrada: {entry or "N/A"}
Stop loss: {stop or "N/A"}
Take profit 2: {tp2 or "N/A"}

Análisis técnico del sistema:
{technical_explanation}

Responde SOLO con el JSON definido en tus reglas."""
