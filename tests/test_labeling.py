"""Triple-barrier: TP primero, SL primero, vertical y ambigüedad."""
import pandas as pd

from trading_bot.core.enums import TradeDirection
from trading_bot.features.ml.labeling import apply_triple_barrier


def _df(rows: list[dict], start: str = "2024-01-01 00:00") -> pd.DataFrame:
    base = pd.Timestamp(start, tz="UTC")
    return pd.DataFrame(
        [
            {
                "timestamp": base + pd.Timedelta(hours=i),
                "open": r.get("open", 100.0),
                "high": r["high"],
                "low": r["low"],
                "close": r.get("close", 100.0),
                "volume": 1.0,
            }
            for i, r in enumerate(rows)
        ]
    )


EVENT_TS = pd.Timestamp("2024-01-01 00:00", tz="UTC")


def test_tp_primero_label_1() -> None:
    df = _df(
        [
            {"high": 100.0, "low": 100.0},  # vela del evento (se excluye: > event_ts)
            {"high": 111.0, "low": 99.0},   # toca TP 110, no SL 95
        ]
    )
    event = apply_triple_barrier(df, EVENT_TS, TradeDirection.LONG, 100.0, 95.0, 110.0)
    assert event.label == 1
    assert event.barrier_hit == "TP"
    assert event.r_outcome == 2.0  # 10 de reward / 5 de riesgo


def test_sl_primero_label_0() -> None:
    df = _df(
        [
            {"high": 100.0, "low": 100.0},
            {"high": 101.0, "low": 94.0},
        ]
    )
    event = apply_triple_barrier(df, EVENT_TS, TradeDirection.LONG, 100.0, 95.0, 110.0)
    assert event.label == 0
    assert event.barrier_hit == "SL"
    assert event.r_outcome == -1.0


def test_vertical_etiqueta_por_signo() -> None:
    rows = [{"high": 101.0, "low": 99.5, "close": 102.0} for _ in range(25)]
    df = _df(rows)
    event = apply_triple_barrier(df, EVENT_TS, TradeDirection.LONG, 100.0, 95.0, 120.0, max_bars=24)
    assert event.barrier_hit == "VERTICAL"
    assert event.label == 1  # cerró arriba de la entrada
    assert event.bars_held == 24

    rows_down = [{"high": 100.5, "low": 98.0, "close": 98.5} for _ in range(25)]
    event_down = apply_triple_barrier(
        _df(rows_down), EVENT_TS, TradeDirection.LONG, 100.0, 95.0, 120.0, max_bars=24
    )
    assert event_down.label == 0


def test_ambiguedad_sin_15m_es_sl() -> None:
    df = _df(
        [
            {"high": 100.0, "low": 100.0},
            {"high": 111.0, "low": 94.0},  # toca ambos
        ]
    )
    event = apply_triple_barrier(df, EVENT_TS, TradeDirection.LONG, 100.0, 95.0, 110.0)
    assert event.barrier_hit == "SL"  # conservador, igual que el backtest


def test_ambiguedad_resuelta_con_15m() -> None:
    df = _df(
        [
            {"high": 100.0, "low": 100.0},
            {"high": 111.0, "low": 94.0},
        ]
    )
    hour = pd.Timestamp("2024-01-01 01:00", tz="UTC")
    df_15m = pd.DataFrame(
        [
            {"timestamp": hour, "open": 100, "high": 111.0, "low": 100.0, "close": 110, "volume": 1},
            {"timestamp": hour + pd.Timedelta(minutes=15), "open": 110, "high": 110.0, "low": 94.0,
             "close": 95, "volume": 1},
        ]
    )
    event = apply_triple_barrier(
        df, EVENT_TS, TradeDirection.LONG, 100.0, 95.0, 110.0, df_15m=df_15m
    )
    assert event.barrier_hit == "TP"


def test_short_funciona_simetrico() -> None:
    df = _df(
        [
            {"high": 100.0, "low": 100.0},
            {"high": 101.0, "low": 89.0},  # SHORT: toca TP 90, no SL 105
        ]
    )
    event = apply_triple_barrier(df, EVENT_TS, TradeDirection.SHORT, 100.0, 105.0, 90.0)
    assert event.label == 1
    assert event.r_outcome == 2.0


def test_sin_velas_futuras_devuelve_none() -> None:
    df = _df([{"high": 100.0, "low": 100.0}])
    assert apply_triple_barrier(df, EVENT_TS, TradeDirection.LONG, 100.0, 95.0, 110.0) is None
