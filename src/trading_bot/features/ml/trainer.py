"""Entrenamiento del meta-modelo LightGBM con gate de despliegue.

El modelo NO se despliega si no demuestra mejora real out-of-sample:
- AUC OOS >= 0.55
- win rate filtrado >= baseline + 5 puntos
- conserva >= 40% de los trades
Si falla el gate, el filtro queda en passthrough y no se pierde nada.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

from trading_bot.features.ml.feature_builder import FEATURE_COLUMNS
from trading_bot.features.ml.validation import PurgedWalkForwardCV

logger = structlog.get_logger()

DEFAULT_PARAMS = {
    "objective": "binary",
    "metric": "auc",
    "num_leaves": 15,
    "min_child_samples": 50,
    "learning_rate": 0.05,
    "n_estimators": 400,
    "verbosity": -1,
    "seed": 42,
}

GATE_MIN_AUC = 0.55
GATE_MIN_WINRATE_UPLIFT = 5.0   # puntos porcentuales
GATE_MIN_TRADES_KEPT = 0.40


@dataclass
class TrainReport:
    deployable: bool
    auc_oos: float
    baseline_win_rate: float
    filtered_win_rate: float
    trades_kept_pct: float
    threshold: float
    n_events: int
    n_splits_used: int
    feature_importance: dict[str, float] = field(default_factory=dict)
    model_path: str | None = None
    trained_at: str | None = None
    gate_failures: list[str] = field(default_factory=list)


class MetaModelTrainer:
    def __init__(self, params: dict | None = None, cv: PurgedWalkForwardCV | None = None) -> None:
        self.params = {**DEFAULT_PARAMS, **(params or {})}
        self.cv = cv or PurgedWalkForwardCV()

    def train(self, dataset: pd.DataFrame, models_dir: Path | str, *, version: str) -> TrainReport:
        """dataset: columnas FEATURE_COLUMNS + label + event_ts."""
        import lightgbm as lgb
        from sklearn.isotonic import IsotonicRegression
        from sklearn.metrics import roc_auc_score

        models_dir = Path(models_dir)
        X = dataset[FEATURE_COLUMNS].to_numpy(dtype=float)
        y = dataset["label"].to_numpy(dtype=int)
        baseline_win_rate = float(y.mean() * 100)

        # 1) CV purgada → predicciones OOS
        oos_pred = np.full(len(y), np.nan)
        splits_used = 0
        for train_idx, test_idx in self.cv.split(dataset):
            if len(np.unique(y[train_idx])) < 2:
                continue
            model = lgb.LGBMClassifier(**self.params)
            model.fit(X[train_idx], y[train_idx])
            oos_pred[test_idx] = model.predict_proba(X[test_idx])[:, 1]
            splits_used += 1

        mask = ~np.isnan(oos_pred)
        if mask.sum() < 80 or len(np.unique(y[mask])) < 2:
            return TrainReport(
                deployable=False,
                auc_oos=0.0,
                baseline_win_rate=baseline_win_rate,
                filtered_win_rate=0.0,
                trades_kept_pct=0.0,
                threshold=0.5,
                n_events=len(y),
                n_splits_used=splits_used,
                gate_failures=["Predicciones OOS insuficientes para evaluar"],
            )

        # 2) Validación ANIDADA temporal: el umbral se elige en el primer 60%
        #    del OOS y la mejora se mide en el 40% final (jamás en el mismo
        #    tramo — elegir y medir en el mismo set deja pasar ruido con suerte).
        oos_idx = np.where(mask)[0]  # dataset ordenado por event_ts
        cut = int(len(oos_idx) * 0.6)
        sel_idx, eval_idx = oos_idx[:cut], oos_idx[cut:]
        if len(eval_idx) < 40 or len(np.unique(y[eval_idx])) < 2:
            return TrainReport(
                deployable=False,
                auc_oos=0.0,
                baseline_win_rate=baseline_win_rate,
                filtered_win_rate=0.0,
                trades_kept_pct=0.0,
                threshold=0.5,
                n_events=len(y),
                n_splits_used=splits_used,
                gate_failures=["Tramo de evaluación insuficiente para validar el umbral"],
            )

        auc = float(roc_auc_score(y[eval_idx], oos_pred[eval_idx]))

        # Calibración y umbral SOLO con el tramo de selección
        calibrator = IsotonicRegression(out_of_bounds="clip")
        calibrated_sel = calibrator.fit_transform(oos_pred[sel_idx], y[sel_idx])
        threshold, _, _ = self._pick_threshold(calibrated_sel, y[sel_idx])

        # La mejora se mide en el tramo de evaluación (nunca visto al elegir)
        calibrated_eval = calibrator.predict(oos_pred[eval_idx])
        kept = calibrated_eval >= threshold
        kept_pct = float(kept.mean() * 100)
        filtered_wr = float(y[eval_idx][kept].mean() * 100) if kept.sum() >= 10 else 0.0
        baseline_win_rate = float(y[eval_idx].mean() * 100)

        # 4) Gate de despliegue
        failures: list[str] = []
        if auc < GATE_MIN_AUC:
            failures.append(f"AUC OOS {auc:.3f} < {GATE_MIN_AUC}")
        if filtered_wr < baseline_win_rate + GATE_MIN_WINRATE_UPLIFT:
            failures.append(
                f"Win rate filtrado {filtered_wr:.1f}% < baseline {baseline_win_rate:.1f}% + {GATE_MIN_WINRATE_UPLIFT}"
            )
        if kept_pct < GATE_MIN_TRADES_KEPT * 100:
            failures.append(f"Conserva {kept_pct:.1f}% de trades < {GATE_MIN_TRADES_KEPT * 100:.0f}%")

        report = TrainReport(
            deployable=not failures,
            auc_oos=round(auc, 4),
            baseline_win_rate=round(baseline_win_rate, 2),
            filtered_win_rate=round(filtered_wr, 2),
            trades_kept_pct=round(kept_pct, 2),
            threshold=round(threshold, 4),
            n_events=len(y),
            n_splits_used=splits_used,
            gate_failures=failures,
        )

        # 5) Solo si pasa el gate: reentrenar con todo y persistir
        if report.deployable:
            final_model = lgb.LGBMClassifier(**self.params)
            final_model.fit(X, y)
            importance = dict(
                zip(FEATURE_COLUMNS, (final_model.feature_importances_ / max(1, final_model.feature_importances_.sum())).round(4).tolist())
            )
            report.feature_importance = {
                k: v for k, v in sorted(importance.items(), key=lambda kv: -kv[1])[:15]
            }

            models_dir.mkdir(parents=True, exist_ok=True)
            model_path = models_dir / f"meta_lgbm_{version}.txt"
            final_model.booster_.save_model(str(model_path))
            import joblib

            joblib.dump(calibrator, models_dir / f"meta_lgbm_{version}.calibrator.joblib")
            meta = {
                "version": version,
                "threshold": report.threshold,
                "feature_columns": FEATURE_COLUMNS,
                "metrics": {
                    "auc_oos": report.auc_oos,
                    "baseline_win_rate": report.baseline_win_rate,
                    "filtered_win_rate": report.filtered_win_rate,
                    "trades_kept_pct": report.trades_kept_pct,
                },
                "trained_at": version,
            }
            (models_dir / f"meta_lgbm_{version}.meta.json").write_text(
                json.dumps(meta, indent=2), encoding="utf-8"
            )
            report.model_path = str(model_path)
            report.trained_at = version
            logger.info("ml_model_deployed", **{k: v for k, v in asdict(report).items() if k != "feature_importance"})
        else:
            logger.warning("ml_model_rejected", failures=failures, auc=auc)

        return report

    @staticmethod
    def _pick_threshold(probs: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
        """Devuelve (umbral, win_rate_filtrado%, trades_conservados%)."""
        best = (0.5, float(y.mean() * 100), 100.0)
        best_score = -1.0
        for threshold in np.arange(0.40, 0.76, 0.01):
            kept = probs >= threshold
            kept_pct = float(kept.mean() * 100)
            if kept_pct < GATE_MIN_TRADES_KEPT * 100 or kept.sum() < 10:
                continue
            wr = float(y[kept].mean() * 100)
            if wr > best_score:
                best_score = wr
                best = (float(threshold), wr, kept_pct)
        return best
