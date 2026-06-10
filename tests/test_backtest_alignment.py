"""slice_mtf: sincronización por timestamp sin lookahead."""
from datetime import UTC, datetime

import pandas as pd

from trading_bot.features.backtest.engine import slice_mtf


def _df(start: str, periods: int, freq: str) -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=periods, freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": dates,
            "open": range(periods),
            "high": range(periods),
            "low": range(periods),
            "close": range(periods),
            "volume": [1.0] * periods,
        }
    )


def test_slice_mtf_no_incluye_vela_4h_en_formacion() -> None:
    df_4h = _df("2024-01-01 00:00", 12, "4h")   # 00:00, 04:00, ..., 44:00
    df_1h = _df("2024-01-01 00:00", 48, "1h")
    df_15m = _df("2024-01-01 00:00", 192, "15min")

    # Cierre de la vela 1H de las 13:00 → "ahora" = 14:00.
    # La vela 4H de las 12:00 cierra a las 16:00: NO debe aparecer.
    t = pd.Timestamp(datetime(2024, 1, 1, 13, 0, tzinfo=UTC))
    ctx = slice_mtf(df_4h, df_1h, df_15m, t, "BTC/USDT")

    assert ctx.df_4h["timestamp"].max() == pd.Timestamp("2024-01-01 08:00", tz="UTC")
    assert ctx.df_1h["timestamp"].max() == t  # la vela 1H 13:00 cierra a las 14:00: incluida


def test_slice_mtf_alinea_15m_por_timestamp() -> None:
    df_4h = _df("2024-01-01 00:00", 12, "4h")
    df_1h = _df("2024-01-01 00:00", 48, "1h")
    df_15m = _df("2024-01-01 00:00", 192, "15min")

    t = pd.Timestamp("2024-01-01 13:00", tz="UTC")
    ctx = slice_mtf(df_4h, df_1h, df_15m, t, "BTC/USDT")
    # "ahora" = 14:00 → la última 15m cerrada es la de las 13:45
    assert ctx.df_15m["timestamp"].max() == pd.Timestamp("2024-01-01 13:45", tz="UTC")


def test_slice_mtf_futuro_excluido_completamente() -> None:
    df_4h = _df("2024-01-01 00:00", 50, "4h")
    df_1h = _df("2024-01-01 00:00", 200, "1h")
    df_15m = _df("2024-01-01 00:00", 800, "15min")

    t = pd.Timestamp("2024-01-03 00:00", tz="UTC")
    ctx = slice_mtf(df_4h, df_1h, df_15m, t, "BTC/USDT")
    now = t + pd.Timedelta(hours=1)
    assert (ctx.df_4h["timestamp"] + pd.Timedelta(hours=4) <= now).all()
    assert (ctx.df_1h["timestamp"] + pd.Timedelta(hours=1) <= now).all()
    assert (ctx.df_15m["timestamp"] + pd.Timedelta(minutes=15) <= now).all()
