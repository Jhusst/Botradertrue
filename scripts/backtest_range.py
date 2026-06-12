"""Backtest de la estrategia de rango sobre histórico real cacheado.

Uso: python scripts/backtest_range.py --symbols BTC/USDT,ETH/USDT
"""
import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.features.backtest.engine import BacktestEngine  # noqa: E402
from trading_bot.features.signals.strategies.range_bollinger_mvp import (  # noqa: E402
    RangeBollingerMVPStrategy,
)
from trading_bot.infrastructure.market_data.history_store import HistoryStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--days", type=int, default=730)
    args = parser.parse_args()

    store = HistoryStore()
    start = datetime.now(UTC) - timedelta(days=args.days)

    for symbol in [s.strip() for s in args.symbols.split(",") if s.strip()]:
        data = store.load_multi_timeframe(symbol, start)
        if any(df.empty for df in data.values()):
            print(f"RESULT|{symbol}|SIN_DATOS")
            continue
        engine = BacktestEngine(strategy=RangeBollingerMVPStrategy())
        m = engine.run(data["4h"], data["1h"], data["15m"], symbol)
        r_multiples = [round(t.r_multiple, 3) for t in m.trades]
        print(
            f"RESULT|{symbol}|trades={m.total_trades}|wr={m.win_rate}|pf={m.profit_factor}"
            f"|dd={m.max_drawdown_percent}|exp_r={round(sum(r_multiples)/len(r_multiples), 4) if r_multiples else 0}"
            f"|net={m.net_pnl_usdt}"
        )


if __name__ == "__main__":
    main()
