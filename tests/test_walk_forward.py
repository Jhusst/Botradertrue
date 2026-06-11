"""WalkForwardRunner: ventanas sin solape, con purga."""
from datetime import UTC, datetime

import pandas as pd

from trading_bot.features.backtest.walk_forward import WalkForwardRunner


def test_ventanas_no_solapan_con_purga() -> None:
    runner = WalkForwardRunner(train_months=6, test_months=1, purge_days=7)
    windows = runner.make_windows(datetime(2023, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC))

    assert len(windows) > 0
    for window in windows:
        # Purga: el test empieza al menos 7 días después del fin del train
        assert window.test_start - window.train_end >= pd.Timedelta(days=7)
        assert window.test_end > window.test_start

    # Los tests de ventanas consecutivas no se solapan entre sí
    for prev, nxt in zip(windows, windows[1:]):
        assert nxt.test_start >= prev.test_end - pd.Timedelta(days=1)


def test_ventanas_avanzan_un_mes() -> None:
    runner = WalkForwardRunner(train_months=6, test_months=1, purge_days=7)
    windows = runner.make_windows(datetime(2023, 1, 1, tzinfo=UTC), datetime(2024, 6, 1, tzinfo=UTC))
    starts = [w.train_start for w in windows]
    for a, b in zip(starts, starts[1:]):
        assert (b - a) == pd.DateOffset(months=1) + a - a  # avanza exactamente 1 mes
        assert b == a + pd.DateOffset(months=1)


def test_reporte_agrega_oos() -> None:
    from trading_bot.features.backtest.engine import BacktestMetrics, TradeRecord
    from trading_bot.features.backtest.walk_forward import (
        WalkForwardReport,
        WalkForwardWindow,
        WindowResult,
    )
    from decimal import Decimal

    def _metrics(pnls: list[float]) -> BacktestMetrics:
        trades = [
            TradeRecord(
                entry_ts=pd.Timestamp("2024-01-01", tz="UTC"),
                direction="LONG",
                grade="A",
                entry=100,
                stop=95,
                tp1=105,
                tp2=110,
                exit_reason="TP2" if p > 0 else "SL",
                pnl_usdt=p,
                r_multiple=p / 5,
                bars_held=3,
            )
            for p in pnls
        ]
        return BacktestMetrics(
            total_trades=len(trades),
            winning_trades=sum(1 for p in pnls if p > 0),
            losing_trades=sum(1 for p in pnls if p <= 0),
            win_rate=Decimal("0"),
            profit_factor=Decimal("0"),
            max_drawdown_percent=Decimal("0"),
            sharpe_ratio=None,
            expectancy=Decimal("0"),
            avg_win_usdt=Decimal("0"),
            avg_loss_usdt=Decimal("0"),
            max_loss_streak=0,
            net_pnl_usdt=Decimal("0"),
            final_balance=Decimal("0"),
            passed_validation=False,
            trades=trades,
        )

    window = WalkForwardWindow(
        train_start=pd.Timestamp("2023-01-01", tz="UTC"),
        train_end=pd.Timestamp("2023-07-01", tz="UTC"),
        test_start=pd.Timestamp("2023-07-08", tz="UTC"),
        test_end=pd.Timestamp("2023-08-08", tz="UTC"),
    )
    report = WalkForwardReport(
        windows=[
            WindowResult(window=window, metrics=_metrics([10.0, -5.0])),
            WindowResult(window=window, metrics=_metrics([20.0])),
        ]
    )
    assert report.total_trades == 3
    assert report.oos_profit_factor == Decimal("6")  # (10+20)/5
    summary = report.summary()
    assert summary["windows"] == 2
