"""Walk-forward: métricas out-of-sample por ventanas con purga.

La estrategia base no se entrena, pero las ventanas OOS muestran si su
rendimiento es ESTABLE en el tiempo o un golpe de suerte de un período.
El runner es reutilizado por el trainer ML (cada ventana entrena con su
train y filtra su test, sin fuga temporal).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import pandas as pd

from trading_bot.features.backtest.engine import BacktestEngine, BacktestMetrics, TradeRecord


@dataclass
class WalkForwardWindow:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp


@dataclass
class WindowResult:
    window: WalkForwardWindow
    metrics: BacktestMetrics


@dataclass
class WalkForwardReport:
    windows: list[WindowResult] = field(default_factory=list)

    @property
    def all_trades(self) -> list[TradeRecord]:
        return [t for w in self.windows for t in w.metrics.trades]

    @property
    def oos_profit_factor(self) -> Decimal:
        wins = sum(t.pnl_usdt for t in self.all_trades if t.pnl_usdt > 0)
        losses = sum(abs(t.pnl_usdt) for t in self.all_trades if t.pnl_usdt <= 0)
        if losses == 0:
            return Decimal("0")
        return Decimal(str(round(wins / losses, 4)))

    @property
    def oos_win_rate(self) -> Decimal:
        trades = self.all_trades
        if not trades:
            return Decimal("0")
        wins = sum(1 for t in trades if t.pnl_usdt > 0)
        return Decimal(str(round(wins / len(trades) * 100, 2)))

    @property
    def total_trades(self) -> int:
        return len(self.all_trades)

    def summary(self) -> dict:
        return {
            "windows": len(self.windows),
            "total_trades_oos": self.total_trades,
            "oos_profit_factor": str(self.oos_profit_factor),
            "oos_win_rate": str(self.oos_win_rate),
            "per_window": [
                {
                    "test_start": str(w.window.test_start),
                    "test_end": str(w.window.test_end),
                    "trades": w.metrics.total_trades,
                    "profit_factor": str(w.metrics.profit_factor),
                    "max_dd": str(w.metrics.max_drawdown_percent),
                }
                for w in self.windows
            ],
        }


class WalkForwardRunner:
    def __init__(
        self,
        engine: BacktestEngine | None = None,
        train_months: int = 6,
        test_months: int = 1,
        purge_days: int = 7,
    ) -> None:
        self.engine = engine or BacktestEngine()
        self.train_months = train_months
        self.test_months = test_months
        self.purge_days = purge_days

    def make_windows(self, start: datetime, end: datetime) -> list[WalkForwardWindow]:
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
        windows: list[WalkForwardWindow] = []
        train_start = start_ts
        while True:
            train_end = train_start + pd.DateOffset(months=self.train_months)
            test_start = train_end + pd.Timedelta(days=self.purge_days)
            test_end = test_start + pd.DateOffset(months=self.test_months)
            if test_end > end_ts:
                break
            windows.append(
                WalkForwardWindow(
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                )
            )
            train_start = train_start + pd.DateOffset(months=self.test_months)
        return windows

    def run(
        self,
        data: dict[str, pd.DataFrame],
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        warmup_bars_1h: int = 200,
    ) -> WalkForwardReport:
        """data: {"4h","1h","15m"} cubriendo [start, end]. Solo cuenta trades del test."""
        report = WalkForwardReport()
        for window in self.make_windows(start, end):
            # Incluir warmup previo al test para que los indicadores estén calientes
            warmup_start = window.test_start - pd.Timedelta(hours=warmup_bars_1h + 8 * 200)
            slices = {
                tf: df[(df["timestamp"] >= warmup_start) & (df["timestamp"] <= window.test_end)]
                .reset_index(drop=True)
                for tf, df in data.items()
            }
            metrics = self.engine.run(slices["4h"], slices["1h"], slices["15m"], symbol)
            # Filtrar trades que de verdad caen dentro de la ventana de test
            test_trades = [
                t
                for t in metrics.trades
                if window.test_start <= t.entry_ts <= window.test_end
            ]
            metrics.trades = test_trades
            metrics.total_trades = len(test_trades)
            report.windows.append(WindowResult(window=window, metrics=metrics))
        return report
