"""Entrena el meta-modelo y lo despliega SOLO si pasa el gate de métricas.

Uso:
    python scripts/build_dataset.py               # primero: construir dataset
    python scripts/retrain_model.py
    python scripts/retrain_model.py --if-due      # solo si pasaron ml_retrain_days
"""
import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from trading_bot.config.settings import get_settings  # noqa: E402
from trading_bot.features.ml.trainer import MetaModelTrainer  # noqa: E402


def _due(models_dir: Path, days: int) -> bool:
    metas = sorted(models_dir.glob("meta_lgbm_*.meta.json"), reverse=True)
    if not metas:
        return True
    age_days = (datetime.now(UTC).timestamp() - metas[0].stat().st_mtime) / 86400
    return age_days >= days


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(Path(settings.data_dir) / "ml" / "dataset.parquet"))
    parser.add_argument("--if-due", action="store_true")
    args = parser.parse_args()

    models_dir = Path(settings.ml_models_dir)
    if args.if_due and not _due(models_dir, settings.ml_retrain_days):
        print("Modelo reciente: no toca reentrenar (--if-due).")
        return

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"No existe {dataset_path}. Corre scripts/build_dataset.py primero.")
        sys.exit(1)

    dataset = pd.read_parquet(dataset_path)
    print(f"Dataset: {len(dataset)} eventos, win rate base {dataset['label'].mean() * 100:.1f}%")

    version = datetime.now(UTC).strftime("%Y%m%d%H%M")
    report = MetaModelTrainer().train(dataset, models_dir, version=version)

    print(json.dumps(
        {
            "deployable": report.deployable,
            "auc_oos": report.auc_oos,
            "baseline_win_rate": report.baseline_win_rate,
            "filtered_win_rate": report.filtered_win_rate,
            "trades_kept_pct": report.trades_kept_pct,
            "threshold": report.threshold,
            "gate_failures": report.gate_failures,
            "model_path": report.model_path,
        },
        indent=2,
    ))
    if not report.deployable:
        print("\nMODELO NO DESPLEGADO: el filtro sigue en passthrough (sin pérdida).")


if __name__ == "__main__":
    main()
