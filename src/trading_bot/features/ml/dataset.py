"""Construcción del dataset de entrenamiento: reproduce la estrategia
vela a vela sobre histórico real y etiqueta cada candidato con triple-barrier.

Incluye TODOS los candidatos con precios (grados A/B/C, incluso los que el
RiskManager filtraría) para maximizar muestras — el modelo aprende qué
separa los que llegan a TP de los que no.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import structlog

from trading_bot.features.backtest.engine import slice_mtf
from trading_bot.features.ml.feature_builder import FEATURE_COLUMNS, FeatureBuilder
from trading_bot.features.ml.labeling import apply_triple_barrier
from trading_bot.features.regime.detector import RegimeDetector
from trading_bot.features.signals.strategies.trend_pullback_mvp import TrendPullbackMVPStrategy

logger = structlog.get_logger()

DATASET_COLUMNS = [*FEATURE_COLUMNS, "label", "r_outcome", "barrier_hit", "event_ts", "symbol"]


class DatasetBuilder:
    def __init__(
        self,
        store=None,
        regime_detector: RegimeDetector | None = None,
        strategy: TrendPullbackMVPStrategy | None = None,
        *,
        use_regime: bool = True,
    ) -> None:
        self.store = store
        self.strategy = strategy or TrendPullbackMVPStrategy()
        self.regime_detector = regime_detector or (RegimeDetector() if use_regime else None)
        self.features = FeatureBuilder()

    def build_from_frames(
        self,
        symbol: str,
        data: dict[str, pd.DataFrame],
        *,
        warmup_bars: int = 200,
        max_bars: int = 24,
    ) -> pd.DataFrame:
        """Genera eventos etiquetados desde {"4h","1h","15m"} ya cargados."""
        df_1h = data["1h"].reset_index(drop=True)
        rows: list[dict] = []
        cooldown_until = -1

        for i in range(warmup_bars, len(df_1h) - 1):
            if i <= cooldown_until:
                continue
            t = df_1h["timestamp"].iloc[i]
            ctx = slice_mtf(data["4h"], df_1h, data["15m"], t, symbol)

            regime = None
            if self.regime_detector is not None:
                try:
                    regime = self.regime_detector.detect(ctx.df_4h, ctx.df_1h)
                    ctx.regime = regime
                except Exception:  # noqa: BLE001
                    regime = None

            out = self.strategy.analyze(ctx)
            if out.direction.value == "NO_TRADE" or not out.entry_price:
                continue

            event = apply_triple_barrier(
                df_1h,
                t,
                out.direction,
                float(out.entry_price),
                float(out.stop_loss),
                float(out.take_profit_2),
                max_bars=max_bars,
                df_15m=data["15m"],
            )
            if event is None:
                continue

            feats = self.features.build(ctx, out, derivatives=None, regime=regime)
            rows.append(
                {
                    **feats,
                    "label": event.label,
                    "r_outcome": event.r_outcome,
                    "barrier_hit": event.barrier_hit,
                    "event_ts": t,
                    "symbol": symbol,
                }
            )
            cooldown_until = i + event.bars_held  # un candidato a la vez por símbolo

        return pd.DataFrame(rows, columns=DATASET_COLUMNS)

    def build(self, symbol: str, start: datetime, end: datetime | None = None) -> pd.DataFrame:
        if self.store is None:
            raise ValueError("Se requiere un HistoryStore para build(); usa build_from_frames() en tests")
        data = self.store.load_multi_timeframe(symbol, start, end)
        if any(df.empty for df in data.values()):
            logger.warning("dataset_missing_history", symbol=symbol)
            return pd.DataFrame(columns=DATASET_COLUMNS)
        return self.build_from_frames(symbol, data)

    def build_multi(
        self, symbols: list[str], start: datetime, end: datetime | None = None,
        *, save_to: Path | str | None = None,
    ) -> pd.DataFrame:
        frames = [self.build(symbol, start, end) for symbol in symbols]
        dataset = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
        if not dataset.empty:
            dataset = dataset.sort_values("event_ts").reset_index(drop=True)
        if save_to is not None and not dataset.empty:
            path = Path(save_to)
            path.parent.mkdir(parents=True, exist_ok=True)
            dataset.to_parquet(path, index=False)
            logger.info("dataset_saved", path=str(path), events=len(dataset))
        return dataset
