"""Cross-validation walk-forward purgada para series temporales de eventos.

Sin fuga: el train de cada split termina ANTES del test, se purgan los
eventos cuya barrera vertical invade el test y se aplica un embargo extra.
"""
from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pandas as pd


class PurgedWalkForwardCV:
    def __init__(self, n_splits: int = 6, embargo_hours: int = 48, barrier_hours: int = 24) -> None:
        self.n_splits = n_splits
        self.embargo_hours = embargo_hours
        self.barrier_hours = barrier_hours

    def split(self, df: pd.DataFrame) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """df debe tener columna event_ts ordenable. Yields (train_idx, test_idx)."""
        ts = pd.to_datetime(df["event_ts"], utc=True).reset_index(drop=True)
        order = ts.sort_values().index.to_numpy()
        n = len(order)
        if n < (self.n_splits + 1) * 2:
            raise ValueError(f"Muy pocos eventos ({n}) para {self.n_splits} splits")

        fold_size = n // (self.n_splits + 1)
        for k in range(1, self.n_splits + 1):
            test_idx = order[k * fold_size : (k + 1) * fold_size if k < self.n_splits else n]
            if len(test_idx) == 0:
                continue
            test_start = ts.iloc[test_idx].min()
            purge_cutoff = test_start - pd.Timedelta(hours=self.embargo_hours + self.barrier_hours)
            train_mask = ts < purge_cutoff
            train_idx = np.asarray(train_mask[train_mask].index)
            if len(train_idx) == 0:
                continue
            yield train_idx, test_idx
