"""Monte Carlo sobre R-multiples: probabilidad de ruina con capital chico.

Block-bootstrap (bloques de K trades) para preservar la autocorrelación de
rachas; equity compuesta con riesgo % fijo por trade. El dato clave para
una cuenta de ~$500: P(drawdown > umbral) y distribución del balance final.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import numpy as np


@dataclass
class MonteCarloReport:
    n_sims: int
    trades_per_sim: int
    median_final_balance: Decimal
    p05_final_balance: Decimal
    p95_final_balance: Decimal
    median_max_dd_pct: Decimal
    p95_max_dd_pct: Decimal
    prob_ruin_pct: Decimal  # P(max drawdown > ruin_threshold)
    prob_loss_pct: Decimal  # P(balance final < inicial)


class MonteCarloSimulator:
    def __init__(
        self,
        n_sims: int = 2000,
        ruin_threshold_pct: float = 30.0,
        block_size: int = 5,
        seed: int | None = None,
    ) -> None:
        self.n_sims = n_sims
        self.ruin_threshold_pct = ruin_threshold_pct
        self.block_size = block_size
        self.seed = seed

    def run(
        self,
        r_multiples: list[float],
        risk_per_trade_pct: float,
        initial_balance: float,
        trades_per_sim: int | None = None,
    ) -> MonteCarloReport:
        if not r_multiples:
            raise ValueError("Se requieren R-multiples de un backtest previo")
        rng = np.random.default_rng(self.seed)
        r = np.asarray(r_multiples, dtype=float)
        n_trades = trades_per_sim or len(r)
        risk_frac = risk_per_trade_pct / 100.0

        finals = np.empty(self.n_sims)
        max_dds = np.empty(self.n_sims)

        n_blocks = max(1, int(np.ceil(n_trades / self.block_size)))
        max_start = max(1, len(r) - self.block_size + 1)

        for sim in range(self.n_sims):
            starts = rng.integers(0, max_start, size=n_blocks)
            sample = np.concatenate([r[s : s + self.block_size] for s in starts])[:n_trades]

            balance = initial_balance
            peak = balance
            max_dd = 0.0
            for r_mult in sample:
                balance += balance * risk_frac * r_mult
                peak = max(peak, balance)
                dd = (peak - balance) / peak * 100
                max_dd = max(max_dd, dd)
                if balance <= 0:
                    balance = 0.0
                    max_dd = 100.0
                    break
            finals[sim] = balance
            max_dds[sim] = max_dd

        def q(arr: np.ndarray, pct: float) -> Decimal:
            return Decimal(str(round(float(np.percentile(arr, pct)), 2)))

        return MonteCarloReport(
            n_sims=self.n_sims,
            trades_per_sim=n_trades,
            median_final_balance=q(finals, 50),
            p05_final_balance=q(finals, 5),
            p95_final_balance=q(finals, 95),
            median_max_dd_pct=q(max_dds, 50),
            p95_max_dd_pct=q(max_dds, 95),
            prob_ruin_pct=Decimal(
                str(round(float((max_dds > self.ruin_threshold_pct).mean() * 100), 2))
            ),
            prob_loss_pct=Decimal(str(round(float((finals < initial_balance).mean() * 100), 2))),
        )
