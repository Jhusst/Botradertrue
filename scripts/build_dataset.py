"""Construye el dataset de meta-labeling desde el histórico cacheado.

Uso:
    python scripts/download_history.py            # primero: descargar histórico
    python scripts/build_dataset.py --symbols BTC/USDT,ETH/USDT --days 730
"""
import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.config.settings import get_settings  # noqa: E402
from trading_bot.features.ml.dataset import DatasetBuilder  # noqa: E402
from trading_bot.infrastructure.market_data.history_store import HistoryStore  # noqa: E402


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=settings.watch_symbols)
    parser.add_argument("--days", type=int, default=settings.history_backfill_days)
    parser.add_argument("--out", default=str(Path(settings.data_dir) / "ml" / "dataset.parquet"))
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    start = datetime.now(UTC) - timedelta(days=args.days)

    builder = DatasetBuilder(store=HistoryStore())
    dataset = builder.build_multi(symbols, start, save_to=args.out)

    if dataset.empty:
        print("Sin eventos. ¿Descargaste el histórico con scripts/download_history.py?")
        return
    print(f"Dataset: {len(dataset)} eventos → {args.out}")
    print(f"  Win rate base: {dataset['label'].mean() * 100:.1f}%")
    print(dataset["barrier_hit"].value_counts().to_string())


if __name__ == "__main__":
    main()
