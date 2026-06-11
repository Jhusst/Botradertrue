"""Backfill de datos históricos reales de Binance a cache local Parquet.

Uso:
    python scripts/download_history.py --symbols BTC/USDT,ETH/USDT --days 730
    python scripts/download_history.py            # watch_symbols del .env, 730 días

No requiere API keys (OHLCV es público).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.config.settings import get_settings  # noqa: E402
from trading_bot.infrastructure.market_data.derivatives_client import (  # noqa: E402
    DerivativesDataClient,
)
from trading_bot.infrastructure.market_data.history_store import HistoryStore  # noqa: E402

TIMEFRAMES = ("4h", "1h", "15m")


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Descarga OHLCV + derivados a cache local")
    parser.add_argument("--symbols", default=settings.watch_symbols)
    parser.add_argument("--days", type=int, default=settings.history_backfill_days)
    parser.add_argument("--skip-derivatives", action="store_true")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    store = HistoryStore()
    derivatives = DerivativesDataClient()

    for symbol in symbols:
        for timeframe in TIMEFRAMES:
            days = args.days if timeframe != "15m" else min(args.days, 400)
            added = store.update(symbol, timeframe, backfill_days=days)
            print(f"  {symbol} {timeframe}: +{added} velas")
        if not args.skip_derivatives:
            counts = derivatives.accumulate(symbol)
            print(f"  {symbol} derivados: {counts}")

    print("Listo. Cache en", store.data_dir.resolve())


if __name__ == "__main__":
    main()
