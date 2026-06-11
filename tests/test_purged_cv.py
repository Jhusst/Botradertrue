"""PurgedWalkForwardCV: orden temporal estricto y embargo sin solape."""
import numpy as np
import pandas as pd
import pytest

from trading_bot.features.ml.validation import PurgedWalkForwardCV


def _events(n: int) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "event_ts": pd.date_range("2023-01-01", periods=n, freq="6h", tz="UTC"),
            "label": np.random.default_rng(1).integers(0, 2, n),
        }
    )


def test_orden_temporal_estricto() -> None:
    df = _events(200)
    cv = PurgedWalkForwardCV(n_splits=4, embargo_hours=48, barrier_hours=24)
    splits = list(cv.split(df))
    assert len(splits) >= 3
    for train_idx, test_idx in splits:
        train_max = df["event_ts"].iloc[train_idx].max()
        test_min = df["event_ts"].iloc[test_idx].min()
        assert train_max < test_min


def test_embargo_elimina_solape() -> None:
    df = _events(200)
    embargo, barrier = 48, 24
    cv = PurgedWalkForwardCV(n_splits=4, embargo_hours=embargo, barrier_hours=barrier)
    for train_idx, test_idx in cv.split(df):
        train_max = df["event_ts"].iloc[train_idx].max()
        test_min = df["event_ts"].iloc[test_idx].min()
        # Ningún evento de train puede tener su barrera (24h) + embargo dentro del test
        assert train_max + pd.Timedelta(hours=embargo + barrier) <= test_min


def test_pocos_eventos_lanza_error() -> None:
    cv = PurgedWalkForwardCV(n_splits=6)
    with pytest.raises(ValueError):
        list(cv.split(_events(5)))
