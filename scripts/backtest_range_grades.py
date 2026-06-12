"""Análisis por grado: ¿las señales A de la estrategia de rango se salvan?"""
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.features.backtest.engine import BacktestEngine  # noqa: E402
from trading_bot.features.signals.strategies.range_bollinger_mvp import (  # noqa: E402
    RangeBollingerMVPStrategy,
)
from trading_bot.infrastructure.market_data.history_store import HistoryStore  # noqa: E402

store = HistoryStore()
start = datetime.now(UTC) - timedelta(days=730)

all_a: list[float] = []
all_b: list[float] = []
for symbol in ("ETH/USDT", "ADA/USDT", "BTC/USDT", "SOL/USDT"):
    data = store.load_multi_timeframe(symbol, start)
    engine = BacktestEngine(strategy=RangeBollingerMVPStrategy())
    metrics = engine.run(data["4h"], data["1h"], data["15m"], symbol)
    a = [t.r_multiple for t in metrics.trades if t.grade == "A"]
    b = [t.r_multiple for t in metrics.trades if t.grade == "B"]
    all_a += a
    all_b += b
    fmt = lambda r: f"n={len(r)} exp={sum(r)/len(r):+.3f}R" if r else "n=0"
    print(f"{symbol}: A[{fmt(a)}]  B[{fmt(b)}]")

fmt = lambda r: f"n={len(r)} exp={sum(r)/len(r):+.3f}R wr={sum(1 for x in r if x > 0)/len(r)*100:.0f}%" if r else "n=0"
print(f"\nAGREGADO  A[{fmt(all_a)}]")
print(f"AGREGADO  B[{fmt(all_b)}]")
