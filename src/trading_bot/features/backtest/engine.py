from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from trading_bot.modules.strategy_engine.trend_pullback_mvp import MarketContext, TrendPullbackMVPStrategy


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


class BacktestEngine:
    """Backtester simplificado para la estrategia MVP."""

    def __init__(
        self,
        initial_balance: Decimal = Decimal("10000"),
        risk_percent: Decimal = Decimal("0.5"),
        commission_rate: Decimal = Decimal("0.0004"),
        slippage_rate: Decimal = Decimal("0.0002"),
        min_profit_factor: Decimal = Decimal("1.3"),
        max_drawdown: Decimal = Decimal("15"),
    ) -> None:
        self.initial_balance = initial_balance
        self.risk_percent = risk_percent
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        self.min_profit_factor = min_profit_factor
        self.max_drawdown = max_drawdown
        self.strategy = TrendPullbackMVPStrategy()

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
        trades_pnl: list[float] = []
        wins: list[float] = []
        losses: list[float] = []
        loss_streak = 0
        max_loss_streak = 0

        window = 200
        for i in range(window, len(df_1h) - 1):
            ctx = MarketContext(
                symbol=symbol,
                df_4h=df_4h.iloc[: i + 1],
                df_1h=df_1h.iloc[: i + 1],
                df_15m=df_15m.iloc[: min(i * 4 + 1, len(df_15m))],
            )
            signal = self.strategy.analyze(ctx)

            if signal.direction.value == "NO_TRADE" or not signal.entry_price:
                continue

            entry = float(signal.entry_price)
            stop = float(signal.stop_loss)
            tp2 = float(signal.take_profit_2)
            risk_per_unit = abs(entry - stop)
            if risk_per_unit == 0:
                continue

            risk_usdt = balance * float(self.risk_percent) / 100
            position = risk_usdt / risk_per_unit

            future = df_1h.iloc[i + 1 : i + 25]
            pnl = 0.0
            hit = False

            for _, candle in future.iterrows():
                if signal.direction.value == "LONG":
                    if candle["low"] <= stop:
                        pnl = -(risk_usdt + position * entry * float(self.commission_rate))
                        hit = True
                        break
                    if candle["high"] >= tp2:
                        reward = abs(tp2 - entry) * position
                        pnl = reward - position * entry * float(self.commission_rate) * 2
                        hit = True
                        break
                else:
                    if candle["high"] >= stop:
                        pnl = -(risk_usdt + position * entry * float(self.commission_rate))
                        hit = True
                        break
                    if candle["low"] <= tp2:
                        reward = abs(entry - tp2) * position
                        pnl = reward - position * entry * float(self.commission_rate) * 2
                        hit = True
                        break

            if not hit:
                continue

            pnl -= abs(pnl) * float(self.slippage_rate)
            balance += pnl
            trades_pnl.append(pnl)
            peak = max(peak, balance)
            dd = (peak - balance) / peak * 100
            max_dd = max(max_dd, dd)

            if pnl > 0:
                wins.append(pnl)
                loss_streak = 0
            else:
                losses.append(abs(pnl))
                loss_streak += 1
                max_loss_streak = max(max_loss_streak, loss_streak)

        total = len(trades_pnl)
        win_count = len(wins)
        loss_count = len(losses)
        gross_profit = sum(wins) if wins else 0
        gross_loss = sum(losses) if losses else 0
        pf = gross_profit / gross_loss if gross_loss > 0 else Decimal("0")
        win_rate = Decimal(str(win_count / total * 100)).quantize(Decimal("0.01")) if total else Decimal("0")
        expectancy = Decimal(str(np.mean(trades_pnl) if trades_pnl else 0)).quantize(Decimal("0.01"))
        sharpe = None
        if len(trades_pnl) > 1:
            std = np.std(trades_pnl)
            if std > 0:
                sharpe = Decimal(str(np.mean(trades_pnl) / std * np.sqrt(252))).quantize(Decimal("0.01"))

        net_pnl = Decimal(str(balance - float(self.initial_balance))).quantize(Decimal("0.01"))
        passed = (
            total >= 30
            and float(pf) >= float(self.min_profit_factor)
            and max_dd <= float(self.max_drawdown)
        )

        return BacktestMetrics(
            total_trades=total,
            winning_trades=win_count,
            losing_trades=loss_count,
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
        )
