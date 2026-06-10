"""Simulación de salidas del BacktestEngine: stop-primero, TP1 parcial, funding."""
from decimal import Decimal

import pandas as pd

from trading_bot.features.backtest.engine import BacktestEngine


def _candles(rows: list[dict]) -> pd.DataFrame:
    base = pd.Timestamp("2024-01-01 00:00", tz="UTC")
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


def test_ambiguedad_sin_15m_resuelve_stop_primero() -> None:
    engine = BacktestEngine()
    # Una vela que toca SL (95) y TP2 (110) a la vez; sin 15m → stop primero
    future = _candles([{"high": 111.0, "low": 94.0}])
    pnl, reason, bars = engine._simulate_exit(
        direction="LONG",
        entry=100.0,
        stop=95.0,
        tp1=105.0,
        tp2=110.0,
        position=1.0,
        future_1h=future,
        df_15m=pd.DataFrame(),
    )
    assert reason == "SL"
    assert pnl == -5.0
    assert bars == 1


def test_ambiguedad_con_15m_puede_resolver_target_primero() -> None:
    engine = BacktestEngine()
    future = _candles([{"high": 111.0, "low": 94.0}])
    # Las 15m muestran que el target se tocó primero (misma hora que la vela 1H: 00:00)
    base = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    df_15m = pd.DataFrame(
        [
            {"timestamp": base, "open": 100, "high": 111.0, "low": 100.0, "close": 110, "volume": 1},
            {"timestamp": base + pd.Timedelta(minutes=15), "open": 110, "high": 110, "low": 94.0,
             "close": 95, "volume": 1},
        ]
    )
    pnl, reason, _ = engine._simulate_exit(
        direction="LONG",
        entry=100.0,
        stop=95.0,
        tp1=105.0,
        tp2=110.0,
        position=1.0,
        future_1h=future,
        df_15m=df_15m,
    )
    assert reason == "TP2"
    # 50% a TP1 (+5*0.5) + 50% a TP2 (+10*0.5) = 7.5
    assert pnl == 7.5


def test_tp1_parcial_luego_stop_a_breakeven() -> None:
    engine = BacktestEngine()
    future = _candles(
        [
            {"high": 106.0, "low": 99.0},   # toca TP1 → mitad cobrada, stop a BE
            {"high": 104.0, "low": 99.5},   # toca BE (100) → resto sale a entry
        ]
    )
    pnl, reason, bars = engine._simulate_exit(
        direction="LONG",
        entry=100.0,
        stop=95.0,
        tp1=105.0,
        tp2=110.0,
        position=1.0,
        future_1h=future,
        df_15m=pd.DataFrame(),
    )
    assert reason == "TP1_BE"
    assert pnl == 2.5  # 0.5 * (105-100)
    assert bars == 2


def test_cierre_vertical_al_vencer_ventana() -> None:
    engine = BacktestEngine()
    # Nunca toca nada: cierre forzado al precio de la última vela
    rows = [{"high": 101.0, "low": 99.5, "close": 100.8} for _ in range(24)]
    future = _candles(rows)
    pnl, reason, bars = engine._simulate_exit(
        direction="LONG",
        entry=100.0,
        stop=95.0,
        tp1=105.0,
        tp2=110.0,
        position=1.0,
        future_1h=future,
        df_15m=pd.DataFrame(),
    )
    assert reason == "VERTICAL"
    assert pnl == 0.7999999999999972 or abs(pnl - 0.8) < 1e-9
    assert bars == 24


def test_funding_resta_pnl() -> None:
    funding = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2024-01-01 08:00", tz="UTC")],
            "funding_rate": [0.001],
        }
    )
    engine = BacktestEngine(include_funding=True, funding_series=funding)
    cost = engine._funding_cost(pd.Timestamp("2024-01-01 00:00", tz="UTC"), 12, 1000.0)
    assert cost == 1.0  # 0.001 * 1000


def test_short_stop_primero() -> None:
    engine = BacktestEngine()
    future = _candles([{"high": 106.0, "low": 89.0}])  # toca stop (105) y tp2 (90)
    pnl, reason, _ = engine._simulate_exit(
        direction="SHORT",
        entry=100.0,
        stop=105.0,
        tp1=95.0,
        tp2=90.0,
        position=1.0,
        future_1h=future,
        df_15m=pd.DataFrame(),
    )
    assert reason == "SL"
    assert pnl == -5.0


def test_run_smoke_con_datos_sinteticos() -> None:
    from trading_bot.infrastructure.market_data.ccxt_client import DataCollector

    data = DataCollector.generate_sample_data(500)
    engine = BacktestEngine(initial_balance=Decimal("10000"))
    metrics = engine.run(data["4h"], data["1h"], data["15m"])
    assert metrics.total_trades >= 0
    assert isinstance(metrics.trades, list)
