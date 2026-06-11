"""Filtro meta-labeling en producción. Sin modelo → passthrough (como el AI gate)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import structlog

from trading_bot.config.settings import Settings, get_settings
from trading_bot.features.ml.feature_builder import FEATURE_COLUMNS

logger = structlog.get_logger()


@dataclass
class MLFilterResult:
    available: bool
    probability: float | None
    passed: bool
    model_version: str | None
    reason: str


class MetaSignalFilter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._booster = None
        self._calibrator = None
        self._threshold: float = self.settings.ml_min_success_probability
        self._version: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self._booster is not None

    def load_latest(self) -> bool:
        """Carga el modelo desplegado más reciente de ml_models_dir."""
        models_dir = Path(self.settings.ml_models_dir)
        if not models_dir.exists():
            return False
        metas = sorted(models_dir.glob("meta_lgbm_*.meta.json"), reverse=True)
        for meta_path in metas:
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("feature_columns") != FEATURE_COLUMNS:
                    logger.warning("ml_model_incompatible_features", path=str(meta_path))
                    continue
                model_path = meta_path.with_suffix("").with_suffix("")  # quita .meta.json
                model_file = Path(str(meta_path).replace(".meta.json", ".txt"))
                if not model_file.exists():
                    continue
                import lightgbm as lgb

                self._booster = lgb.Booster(model_file=str(model_file))
                self._threshold = float(meta.get("threshold", self._threshold))
                self._version = meta.get("version")
                calib_file = Path(str(meta_path).replace(".meta.json", ".calibrator.joblib"))
                if calib_file.exists():
                    import joblib

                    self._calibrator = joblib.load(calib_file)
                logger.info("ml_model_loaded", version=self._version, threshold=self._threshold)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("ml_model_load_failed", path=str(meta_path), error=str(exc))
        return False

    def evaluate(self, features: dict[str, float]) -> MLFilterResult:
        if not self.is_loaded and not self.load_latest():
            return MLFilterResult(
                available=False,
                probability=None,
                passed=True,
                model_version=None,
                reason="Sin modelo desplegado: passthrough",
            )
        try:
            import numpy as np

            row = np.array([[features.get(c, float("nan")) for c in FEATURE_COLUMNS]], dtype=float)
            raw = float(self._booster.predict(row)[0])
            prob = raw
            if self._calibrator is not None:
                prob = float(self._calibrator.predict([raw])[0])
            passed = prob >= self._threshold
            return MLFilterResult(
                available=True,
                probability=round(prob, 4),
                passed=passed,
                model_version=self._version,
                reason=f"p_exito={prob:.2f} {'≥' if passed else '<'} umbral {self._threshold:.2f}",
            )
        except Exception as exc:  # noqa: BLE001 — el filtro nunca rompe el flujo
            logger.warning("ml_predict_failed", error=str(exc))
            return MLFilterResult(
                available=False,
                probability=None,
                passed=True,
                model_version=self._version,
                reason=f"Error en predicción: passthrough ({exc})",
            )
