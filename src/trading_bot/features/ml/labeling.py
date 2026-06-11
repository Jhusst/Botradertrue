"""Triple-barrier (López de Prado) con las barreras REALES del candidato.

El modelo aprende exactamente la pregunta operativa: ¿este setup concreto
alcanza su TP2 antes que su SL dentro de la ventana? Misma resolución
intrabar 15m / stop-primero que el BacktestEngine (consistencia total).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.core.enums import TradeDirection


@dataclass(frozen=True)
class LabeledEvent:
    event_ts: pd.Timestamp
    label: int                # 1 = TP primero / vertical positivo; 0 = SL / vertical negativo
    r_outcome: float          # resultado en R-multiples
    bars_held: int
    barrier_hit: str          # "TP" | "SL" | "VERTICAL"


def apply_triple_barrier(
    df_1h: pd.DataFrame,
    event_ts: pd.Timestamp,
    direction: TradeDirection,
    entry: float,
    stop: float,
    target: float,
    max_bars: int = 24,
    df_15m: pd.DataFrame | None = None,
) -> LabeledEvent | None:
    """Etiqueta un candidato. None si no hay velas futuras suficientes (>=1)."""
    is_long = direction == TradeDirection.LONG
    risk = abs(entry - stop)
    if risk <= 0:
        return None

    future = df_1h[df_1h["timestamp"] > event_ts].head(max_bars)
    if future.empty:
        return None

    for n, (_, candle) in enumerate(future.iterrows(), start=1):
        hit_stop = candle["low"] <= stop if is_long else candle["high"] >= stop
        hit_target = candle["high"] >= target if is_long else candle["low"] <= target

        if hit_stop and hit_target:
            first = _first_touch_15m(candle["timestamp"], df_15m, is_long, stop, target)
            if first == "STOP":
                hit_target = False
            else:
                hit_stop = False

        if hit_stop:
            return LabeledEvent(
                event_ts=event_ts, label=0, r_outcome=-1.0, bars_held=n, barrier_hit="SL"
            )
        if hit_target:
            r = abs(target - entry) / risk
            return LabeledEvent(
                event_ts=event_ts, label=1, r_outcome=r, bars_held=n, barrier_hit="TP"
            )

    # Barrera vertical: etiqueta por el signo del retorno al cierre
    last_close = float(future["close"].iloc[-1])
    diff = (last_close - entry) if is_long else (entry - last_close)
    r = diff / risk
    return LabeledEvent(
        event_ts=event_ts,
        label=1 if r > 0 else 0,
        r_outcome=r,
        bars_held=len(future),
        barrier_hit="VERTICAL",
    )


def _first_touch_15m(
    hour_ts: pd.Timestamp,
    df_15m: pd.DataFrame | None,
    is_long: bool,
    stop: float,
    target: float,
) -> str:
    """Misma regla que el BacktestEngine: ambigüedad sin datos → STOP (conservador)."""
    if df_15m is None or df_15m.empty:
        return "STOP"
    window = df_15m[
        (df_15m["timestamp"] >= hour_ts) & (df_15m["timestamp"] < hour_ts + pd.Timedelta(hours=1))
    ]
    for _, candle in window.iterrows():
        hit_stop = candle["low"] <= stop if is_long else candle["high"] >= stop
        hit_target = candle["high"] >= target if is_long else candle["low"] <= target
        if hit_stop:
            return "STOP"
        if hit_target:
            return "TARGET"
    return "STOP"
