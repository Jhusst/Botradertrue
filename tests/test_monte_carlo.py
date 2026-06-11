"""MonteCarloSimulator: determinismo con seed, riesgo↑ → ruina↑."""
import pytest

from trading_bot.features.backtest.monte_carlo import MonteCarloSimulator

# R-multiples plausibles: 40% winners de +2R, 60% losers de -1R
R_SAMPLE = [2.0] * 40 + [-1.0] * 60


def test_distribucion_determinista_con_seed() -> None:
    sim1 = MonteCarloSimulator(n_sims=200, seed=42)
    sim2 = MonteCarloSimulator(n_sims=200, seed=42)
    r1 = sim1.run(R_SAMPLE, risk_per_trade_pct=0.5, initial_balance=500)
    r2 = sim2.run(R_SAMPLE, risk_per_trade_pct=0.5, initial_balance=500)
    assert r1.median_final_balance == r2.median_final_balance
    assert r1.prob_ruin_pct == r2.prob_ruin_pct


def test_prob_ruina_aumenta_con_riesgo() -> None:
    sim = MonteCarloSimulator(n_sims=500, ruin_threshold_pct=30.0, seed=7)
    conservador = sim.run(R_SAMPLE, risk_per_trade_pct=0.5, initial_balance=500)
    sim2 = MonteCarloSimulator(n_sims=500, ruin_threshold_pct=30.0, seed=7)
    agresivo = sim2.run(R_SAMPLE, risk_per_trade_pct=5.0, initial_balance=500)
    assert agresivo.prob_ruin_pct > conservador.prob_ruin_pct
    assert agresivo.p95_max_dd_pct > conservador.p95_max_dd_pct


def test_riesgo_conservador_con_edge_no_arruina() -> None:
    sim = MonteCarloSimulator(n_sims=500, ruin_threshold_pct=30.0, seed=11)
    report = sim.run(R_SAMPLE, risk_per_trade_pct=0.5, initial_balance=500)
    # Con +2R/40% y 0.5% por trade la ruina del 30% debe ser despreciable
    assert float(report.prob_ruin_pct) < 1.0
    assert report.median_final_balance > 500


def test_sin_trades_lanza_error() -> None:
    sim = MonteCarloSimulator(n_sims=10)
    with pytest.raises(ValueError):
        sim.run([], risk_per_trade_pct=0.5, initial_balance=500)
