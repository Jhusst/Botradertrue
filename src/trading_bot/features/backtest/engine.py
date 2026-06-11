"""Backtester multi-timeframe sin lookahead.

Cambios clave vs la versión inicial:
- Sincronización 4H/1H/15M por TIMESTAMP (no por índice i*4): a la vela 1H
  de las 13:00 le corresponde la última vela 4H CERRADA antes de esa hora.
- Fills intrabar con 15m: si una vela 1H toca SL y TP a la vez, las velas
  de 15m de esa hora deciden el orden; sin 15m se asume STOP PRIMERO (conservador).
- Salida en dos tramos: 50% en TP1 + stop a breakeven, 50% en TP2 — igual
  que la operativa real del bot. Cierre forzado a las 24 velas 1H.
- Hook signal_filter(strategy_output, ctx) -> (permitir, probabilidad) para
  enchufar el filtro ML sin tocar el motor.
- Comisión taker por lado + slippage + funding opcional.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
import pandas as pd

from trading_bot.features.signals.strategies.trend_pullback_mvp import (
    MarketContext,
    StrategyOutput,
    TrendPullbackMVPStrategy,
)

SignalFilter = Callable[[StrategyOutput, MarketContext], tuple[bool, float | None]]

MAX_HOLD_BARS_1H = 24


@dataclass
class TradeRecord:
    entry_ts: pd.Timestamp
    direction: str
    grade: str
    entry: float
    stop: float
    tp1: float
    tp2: float
    exit_reason: str  # SL | TP2 | TP1_BE | VERTICAL
    pnl_usdt: float
    r_multiple: float
    bars_held: int
    ml_probability: float | None = None


@dataclass
class BacktestMetrics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    profit_factor: Decimal
    max_drawdown_percent: Decimal
    sharpe_ratio: Decimal | None
    expectancy: Decimal
    avg_win_usdt: Decimal
    avg_loss_usdt: Decimal
    max_loss_streak: int
    net_pnl_usdt: Decimal
    final_balance: Decimal
    passed_validation: bool
    trades: list[TradeRecord] = field(default_factory=list)


def slice_mtf(
    df_4h: pd.DataFrame, df_1h: pd.DataFrame, df_15m: pd.DataFrame, t: pd.Timestamp, symbol: str
) -> MarketContext:
    """Contexto SIN lookahead en el instante t (cierre de la vela 1H con timestamp t).

    Una vela con timestamp T cubre [T, T+tf): está cerrada cuando now >= T+tf.
    En el cierre de la vela 1H t, el "ahora" es t + 1h.
    """
    now = t + pd.Timedelta(hours=1)
    closed_4h = df_4h[df_4h["timestamp"] + pd.Timedelta(hours=4) <= now]
    closed_1h = df_1h[df_1h["timestamp"] + pd.Timedelta(hours=1) <= now]
    closed_15m = df_15m[df_15m["timestamp"] + pd.Timedelta(minutes=15) <= now]
    return MarketContext(symbol=symbol, df_4h=closed_4h, df_1h=closed_1h, df_15m=closed_15m)


class BacktestEngine:
    """Backtester para la estrategia MVP con simulación de salidas realista."""

    def __init__(
        self,
        initial_balance: Decimal = Decimal("10000"),
        risk_percent: Decimal = Decimal("0.5"),
        commission_rate: Decimal = Decimal("0.0005"),
        slippage_rate: Decimal = Decimal("0.0002"),
        min_profit_factor: Decimal = Decimal("1.3"),
        max_drawdown: Decimal = Decimal("15"),
        include_funding: bool = False,
        funding_series: pd.DataFrame | None = None,
        signal_filter: SignalFilter | None = None,
        strategy: TrendPullbackMVPStrategy | None = None,
    ) -> None:
        self.initial_balance = initial_balance
        self.risk_percent = risk_percent
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.min_profit_factor = min_profit_factor
        self.max_drawdown = max_drawdown
        self.include_funding = include_funding
        self.funding_series = funding_series
        self.signal_filter = signal_filter
        self.strategy = strategy or TrendPullbackMVPStrategy()

    # ------------------------------------------------------------------

    def run(
        self,
        df_4h: pd.DataFrame,
        df_1h: pd.DataFrame,
        df_15m: pd.DataFrame,
        symbol: str = "BTC/USDT",
    ) -> BacktestMetrics:
        balance = float(self.initial_balance)
        peak = balance
        max_dd = 0.0
        records: list[TradeRecord] = []
        loss_streak = 0
        max_loss_streak = 0
        commission = float(self.commission_rate)
        slippage = float(self.slippage_rate)

        df_1h = df_1h.reset_index(drop=True)
        in_trade_until = -1  # evita solapar trades

        window = 200
        for i in range(window, len(df_1h) - 1):
            if i <= in_trade_until:
                continue
            t = df_1h["timestamp"].iloc[i]
            ctx = slice_mtf(df_4h, df_1h, df_15m, t, symbol)
            signal = self.strategy.analyze(ctx)

            if signal.direction.value == "NO_TRADE" or not signal.entry_price:
                continue

            ml_probability: float | None = None
            if self.signal_filter is not None:
                allowed, ml_probability = self.signal_filter(signal, ctx)
                if not allowed:
                    continue

            entry = float(signal.entry_price)
            stop = float(signal.stop_loss)
            tp1 = float(signal.take_profit_1)
            tp2 = float(signal.take_profit_2)
            risk_per_unit = abs(entry - stop)
            if risk_per_unit == 0:
                continue

            risk_usdt = balance * float(self.risk_percent) / 100
            position = risk_usdt / risk_per_unit

            future = df_1h.iloc[i + 1 : i + 1 + MAX_HOLD_BARS_1H]
            pnl, exit_reason, bars_held = self._simulate_exit(
                direction=signal.direction.value,
                entry=entry,
                stop=stop,
                tp1=tp1,
                tp2=tp2,
                position=position,
                future_1h=future,
                df_15m=df_15m,
            )
            if exit_reason == "NONE":
                continue

            # Comisión entrada+salida sobre el notional, slippage sobre el PnL
            pnl -= position * entry * commission * 2
            pnl -= abs(pnl) * slippage
            if self.include_funding:
                pnl -= self._funding_cost(t, bars_held, position * entry)

            balance += pnl
            peak = max(peak, balance)
            dd = (peak - balance) / peak * 100
            max_dd = max(max_dd, dd)

            if pnl > 0:
                loss_streak = 0
            else:
                loss_streak += 1
                max_loss_streak = max(max_loss_streak, loss_streak)

            records.append(
                TradeRecord(
                    entry_ts=t,
                    direction=signal.direction.value,
                    grade=signal.setup_grade.value,
                    entry=entry,
                    stop=stop,
                    tp1=tp1,
                    tp2=tp2,
                    exit_reason=exit_reason,
                    pnl_usdt=pnl,
                    r_multiple=pnl / risk_usdt if risk_usdt > 0 else 0.0,
                    bars_held=bars_held,
                    ml_probability=ml_probability,
                )
            )
            in_trade_until = i + bars_held

        return self._build_metrics(records, balance, max_dd, max_loss_streak)

    # ------------------------------------------------------------------

    def _simulate_exit(
        self,
        *,
        direction: str,
        entry: float,
        stop: float,
        tp1: float,
        tp2: float,
        position: float,
        future_1h: pd.DataFrame,
        df_15m: pd.DataFrame,
    ) -> tuple[float, str, int]:
        """Salida en dos tramos. Devuelve (pnl_bruto, motivo, velas_1h)."""
        is_long = direction == "LONG"
        half = position / 2
        tp1_hit = False
        current_stop = stop

        for n, (_, candle) in enumerate(future_1h.iterrows(), start=1):
            hit_stop = candle["low"] <= current_stop if is_long else candle["high"] >= current_stop
            hit_tp1 = (not tp1_hit) and (
                candle["high"] >= tp1 if is_long else candle["low"] <= tp1
            )
            hit_tp2 = candle["high"] >= tp2 if is_long else candle["low"] <= tp2

            # Ambigüedad dentro de la vela: resolver con 15m; sin datos → stop primero
            if hit_stop and (hit_tp1 or hit_tp2):
                first = self._first_touch_15m(
                    candle["timestamp"], df_15m, is_long, current_stop, tp2 if hit_tp2 else tp1
                )
                if first == "STOP":
                    hit_tp1 = hit_tp2 = False
                else:
                    hit_stop = False

            if hit_stop:
                if tp1_hit:
                    # Mitad ya cobrada en TP1; la otra mitad sale a breakeven
                    pnl = half * abs(tp1 - entry)
                    return pnl, "TP1_BE", n
                return -position * abs(entry - current_stop), "SL", n

            if hit_tp2:
                if tp1_hit:
                    pnl = half * abs(tp1 - entry) + half * abs(tp2 - entry)
                else:
                    # La misma vela alcanzó TP1 y TP2
                    pnl = half * abs(tp1 - entry) + half * abs(tp2 - entry)
                return pnl, "TP2", n

            if hit_tp1:
                tp1_hit = True
                current_stop = entry  # breakeven para el resto

        # Cierre forzado al vencer la ventana (precio de cierre de la última vela)
        if len(future_1h) == 0:
            return 0.0, "NONE", 0
        last_close = float(future_1h["close"].iloc[-1])
        diff = (last_close - entry) if is_long else (entry - last_close)
        if tp1_hit:
            pnl = half * abs(tp1 - entry) + half * diff
        else:
            pnl = position * diff
        return pnl, "VERTICAL", len(future_1h)

    @staticmethod
    def _first_touch_15m(
        hour_ts: pd.Timestamp,
        df_15m: pd.DataFrame,
        is_long: bool,
        stop: float,
        target: float,
    ) -> str:
        """¿Qué tocó primero la hora ambigua: STOP o TARGET? Conservador: STOP."""
        if df_15m is None or df_15m.empty:
            return "STOP"
        window = df_15m[
            (df_15m["timestamp"] >= hour_ts)
            & (df_15m["timestamp"] < hour_ts + pd.Timedelta(hours=1))
        ]
        for _, candle in window.iterrows():
            hit_stop = candle["low"] <= stop if is_long else candle["high"] >= stop
            hit_target = candle["high"] >= target if is_long else candle["low"] <= target
            if hit_stop and hit_target:
                return "STOP"
            if hit_stop:
                return "STOP"
            if hit_target:
                return "TARGET"
        return "STOP"

    def _funding_cost(self, entry_ts: pd.Timestamp, bars_held: int, notional: float) -> float:
        if self.funding_series is None or self.funding_series.empty:
            return 0.0
        window = self.funding_series[
            (self.funding_series["timestamp"] >= entry_ts)
            & (self.funding_series["timestamp"] <= entry_ts + pd.Timedelta(hours=bars_held))
        ]
        if window.empty:
            return 0.0
        return float(window["funding_rate"].sum()) * notional

    # ------------------------------------------------------------------

    def _build_metrics(
        self,
        records: list[TradeRecord],
        balance: float,
        max_dd: float,
        max_loss_streak: int,
    ) -> BacktestMetrics:
        trades_pnl = [r.pnl_usdt for r in records]
        wins = [p for p in trades_pnl if p > 0]
        losses = [abs(p) for p in trades_pnl if p <= 0]
        total = len(trades_pnl)
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = sum(losses) if losses else 0.0
        pf = gross_profit / gross_loss if gross_loss > 0 else 0.0
        win_rate = (
            Decimal(str(len(wins) / total * 100)).quantize(Decimal("0.01")) if total else Decimal("0")
        )
        expectancy = Decimal(str(np.mean(trades_pnl) if trades_pnl else 0)).quantize(Decimal("0.01"))
        sharpe = None
        if len(trades_pnl) > 1:
            std = np.std(trades_pnl)
            if std > 0:
                sharpe = Decimal(str(np.mean(trades_pnl) / std * np.sqrt(252))).quantize(
                    Decimal("0.01")
                )

        net_pnl = Decimal(str(balance - float(self.initial_balance))).quantize(Decimal("0.01"))
        passed = (
            total >= 30
            and pf >= float(self.min_profit_factor)
            and max_dd <= float(self.max_drawdown)
        )

        return BacktestMetrics(
            total_trades=total,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate=win_rate,
            profit_factor=Decimal(str(round(pf, 4))),
            max_drawdown_percent=Decimal(str(round(max_dd, 4))),
            sharpe_ratio=sharpe,
            expectancy=expectancy,
            avg_win_usdt=Decimal(str(round(np.mean(wins), 2))) if wins else Decimal("0"),
            avg_loss_usdt=Decimal(str(round(np.mean(losses), 2))) if losses else Decimal("0"),
            max_loss_streak=max_loss_streak,
            net_pnl_usdt=net_pnl,
            final_balance=Decimal(str(round(balance, 2))),
            passed_validation=passed,
            trades=records,
        )
