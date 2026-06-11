"""MetaSignalFilter y MetaModelTrainer: passthrough, gate de despliegue, filtro."""
import numpy as np
import pandas as pd
import pytest

from trading_bot.config.settings import Settings, get_settings
from trading_bot.features.ml.feature_builder import FEATURE_COLUMNS
from trading_bot.features.ml.predictor import MetaSignalFilter
from trading_bot.features.ml.trainer import MetaModelTrainer


def _settings(tmp_path, **overrides) -> Settings:
    data = get_settings().model_dump()
    defaults = {"ml_filter_enabled": True, "ml_models_dir": str(tmp_path)}
    data.update({**defaults, **overrides})
    return Settings(**data)


def _separable_dataset(n: int = 600) -> pd.DataFrame:
    """Dataset sintético separable: rsi_1h alto → gana; bajo → pierde."""
    rng = np.random.default_rng(7)
    df = pd.DataFrame(np.nan, index=range(n), columns=FEATURE_COLUMNS)
    rsi = rng.uniform(20, 80, n)
    df["rsi_1h"] = rsi
    df["adx_4h"] = rng.uniform(10, 40, n)
    df["direction_long"] = rng.integers(0, 2, n).astype(float)
    df["label"] = (rsi > 50).astype(int)
    # Pequeño ruido en el label para realismo
    flip = rng.random(n) < 0.05
    df.loc[flip, "label"] = 1 - df.loc[flip, "label"]
    df["event_ts"] = pd.date_range("2023-01-01", periods=n, freq="4h", tz="UTC")
    return df


def _hopeless_dataset(n: int = 600) -> pd.DataFrame:
    """Dataset sin señal: features puro ruido, labels aleatorios."""
    rng = np.random.default_rng(11)
    df = pd.DataFrame(rng.normal(0, 1, (n, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    df["label"] = rng.integers(0, 2, n)
    df["event_ts"] = pd.date_range("2023-01-01", periods=n, freq="4h", tz="UTC")
    return df


def test_sin_modelo_passthrough(tmp_path) -> None:
    flt = MetaSignalFilter(_settings(tmp_path))
    result = flt.evaluate(dict.fromkeys(FEATURE_COLUMNS, 0.5))
    assert result.available is False
    assert result.passed is True  # nunca bloquea sin modelo


def test_trainer_despliega_modelo_bueno_y_filtro_funciona(tmp_path) -> None:
    settings = _settings(tmp_path)
    report = MetaModelTrainer().train(_separable_dataset(), tmp_path, version="testv1")
    assert report.deployable is True
    assert report.auc_oos > 0.8
    assert report.model_path is not None

    flt = MetaSignalFilter(settings)
    good = dict.fromkeys(FEATURE_COLUMNS, float("nan"))
    good.update({"rsi_1h": 75.0, "adx_4h": 30.0, "direction_long": 1.0})
    bad = dict.fromkeys(FEATURE_COLUMNS, float("nan"))
    bad.update({"rsi_1h": 25.0, "adx_4h": 30.0, "direction_long": 1.0})

    good_result = flt.evaluate(good)
    bad_result = flt.evaluate(bad)
    assert good_result.available and bad_result.available
    assert good_result.probability > bad_result.probability
    assert good_result.passed is True
    assert bad_result.passed is False


def test_gate_rechaza_modelo_sin_senal(tmp_path) -> None:
    report = MetaModelTrainer().train(_hopeless_dataset(), tmp_path, version="testv2")
    assert report.deployable is False
    assert report.gate_failures
    assert report.model_path is None
    # Y el filtro queda en passthrough
    flt = MetaSignalFilter(_settings(tmp_path))
    result = flt.evaluate(dict.fromkeys(FEATURE_COLUMNS, 0.0))
    assert result.available is False
    assert result.passed is True


def test_generator_no_trade_por_ml(tmp_path) -> None:
    """Modo filter: el generator rechaza señales con probabilidad baja."""
    from decimal import Decimal
    from unittest.mock import MagicMock, patch

    from trading_bot.core.enums import SetupGrade, TradeDirection
    from trading_bot.features.ml.predictor import MLFilterResult
    from trading_bot.features.signals.generator import SignalGenerator
    from trading_bot.features.signals.strategies.trend_pullback_mvp import (
        MarketContext,
        StrategyOutput,
    )
    from trading_bot.infrastructure.market_data.ccxt_client import DataCollector
    from trading_bot.schemas.risk import AccountRiskState

    settings = _settings(tmp_path, ml_filter_mode="filter", regime_detection_enabled=False)

    data = DataCollector.generate_sample_data(500)
    ctx = MarketContext(symbol="BTC/USDT", df_4h=data["4h"], df_1h=data["1h"], df_15m=data["15m"])
    account = AccountRiskState(balance_usdt=Decimal("500"), min_setup_grade="B")

    # Estrategia mockeada: candidato grado A válido que SÍ pasa el RiskManager
    setup_a = StrategyOutput(
        direction=TradeDirection.LONG,
        setup_grade=SetupGrade.A,
        primary_timeframe="1h",
        entry_price=Decimal("50000"),
        stop_loss=Decimal("49000"),
        take_profit_1=Decimal("51000"),
        take_profit_2=Decimal("52000"),
        confidence_score=Decimal("85"),
        technical_explanation="mock",
        invalidation_conditions="mock",
        atr_percent=Decimal("1.5"),
    )
    generator = SignalGenerator()
    generator.crypto_strategy = MagicMock(analyze=MagicMock(return_value=setup_a), STRATEGY_NAME="Mock")

    ml_filter = MagicMock()
    ml_filter.evaluate.return_value = MLFilterResult(
        available=True, probability=0.2, passed=False, model_version="testv3",
        reason="p_exito=0.20 < umbral",
    )
    generator._ml_filter = ml_filter

    with patch("trading_bot.features.signals.generator.get_settings", return_value=settings):
        signal = generator.generate(ctx, account)

    assert signal.should_trade is False
    assert "Filtro ML" in (signal.rejection_reason or "")

    # Modo advise: la misma probabilidad baja NO bloquea, solo ajusta confianza
    settings_advise = _settings(tmp_path, ml_filter_mode="advise", regime_detection_enabled=False)
    with patch("trading_bot.features.signals.generator.get_settings", return_value=settings_advise):
        signal_advise = generator.generate(ctx, account)
    assert signal_advise.should_trade is True
    assert signal_advise.ml_probability == 0.2
    assert signal_advise.confidence_score < Decimal("85")  # ajustada a la baja
