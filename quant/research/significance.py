"""Is this backtest distinguishable from luck? (Phase 08b)

Two independent, resampling-based answers, both pure functions over the
outputs phase 05 already produces:

:func:`monte_carlo_permutation_test`
    Shuffles the ORDER of realised trade P&Ls many times and asks how often a
    random ordering beats the observed result. Path-dependent statistics --
    drawdown, the shape of the equity curve -- depend on sequence; the total
    P&L does not. So this test says nothing about whether the average trade is
    profitable, and everything about whether the *path* was luckier than a
    coin-flip ordering of the same trades.

:func:`bootstrap_sharpe_ci`
    Resamples the daily returns series with replacement to put a confidence
    interval around the Sharpe ratio. A Sharpe of 1.8 whose 95% interval spans
    [-0.4, 3.9] is one month of noise, not an edge, and the point estimate
    alone never says so.

Both are seeded and therefore reproducible: the same inputs and the same
``seed`` give identical output, which is what makes them safe to embed in a
run card.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from quant.research._stats import TRADING_DAYS_PER_YEAR, sharpe_ratio

DEFAULT_ITERATIONS = 1_000
DEFAULT_SEED = 20260831
SUPPORTED_STATISTICS = ("max_drawdown_pct", "sharpe", "final_equity", "total_pnl")


@dataclass(frozen=True)
class PermutationResult:
    """Outcome of a Monte Carlo permutation test on one statistic."""

    statistic: str
    observed: float
    p_value: float
    iterations: int
    seed: int
    null_mean: float
    null_std: float
    null_percentiles: dict[str, float] = field(default_factory=dict)

    @property
    def significant_at_5pct(self) -> bool:
        return self.p_value < 0.05

    def to_dict(self) -> dict[str, object]:
        return {
            "statistic": self.statistic,
            "observed": self.observed,
            "p_value": self.p_value,
            "iterations": self.iterations,
            "seed": self.seed,
            "null_mean": self.null_mean,
            "null_std": self.null_std,
            "null_percentiles": dict(self.null_percentiles),
            "significant_at_5pct": self.significant_at_5pct,
        }


@dataclass(frozen=True)
class BootstrapResult:
    """Bootstrap confidence interval around an annualised Sharpe ratio."""

    observed_sharpe: float
    lower: float
    upper: float
    confidence: float
    iterations: int
    seed: int
    standard_error: float
    prob_positive: float

    @property
    def excludes_zero(self) -> bool:
        """True when the whole interval sits above zero."""
        return self.lower > 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "observed_sharpe": self.observed_sharpe,
            "ci_lower": self.lower,
            "ci_upper": self.upper,
            "confidence": self.confidence,
            "iterations": self.iterations,
            "seed": self.seed,
            "standard_error": self.standard_error,
            "prob_positive": self.prob_positive,
            "excludes_zero": self.excludes_zero,
        }


def _equity_path(pnls: np.ndarray, initial_capital: float) -> np.ndarray:
    return initial_capital + np.cumsum(pnls)


def _max_drawdown_pct(path: np.ndarray) -> float:
    peaks = np.maximum.accumulate(path)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peaks > 0, (peaks - path) / peaks, 0.0)
    return float(np.max(dd)) if dd.size else 0.0


def _path_statistic(pnls: np.ndarray, statistic: str, initial_capital: float) -> float:
    """Value of ``statistic`` for one ordering of the same trade P&Ls."""
    if statistic == "total_pnl":
        # math.fsum, not np.sum: float addition is not associative, so a
        # plain sum of a shuffled array differs from the original in the last
        # bits and the order-invariant statistic would report a p-value
        # scattered around 0.5 instead of the exact 1.0 that says "this
        # statistic cannot detect ordering".
        return math.fsum(pnls.tolist())
    path = _equity_path(pnls, initial_capital)
    if statistic == "max_drawdown_pct":
        # Negated so "larger is better" holds for every statistic here, which
        # keeps the one-sided p-value definition below uniform.
        return -_max_drawdown_pct(path)
    if statistic == "final_equity":
        return float(path[-1])
    if statistic == "sharpe":
        prev = np.concatenate(([initial_capital], path[:-1]))
        rets = (path - prev) / np.maximum(prev, 1e-12)
        return sharpe_ratio(rets.tolist())
    raise ValueError(f"unknown statistic: {statistic!r}")


def monte_carlo_permutation_test(
    trade_pnls: Sequence[float],
    *,
    statistic: str = "max_drawdown_pct",
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
    initial_capital: float = 1_000_000.0,
) -> PermutationResult:
    """How often does a random re-ordering of these trades beat the real one?

    The null hypothesis is that trade order carries no information: the same
    P&Ls in any sequence are equally likely. Under that null, ``iterations``
    shuffled orderings give the distribution of ``statistic``; the p-value is
    the share of them that match or beat what actually happened.

    ``statistic="total_pnl"`` is accepted but degenerate on purpose -- the sum
    is invariant to ordering, so it always returns ``p == 1.0``. It exists so
    a caller sweeping every statistic gets an obvious signal rather than a
    subtly wrong one.

    Raises ``ValueError`` for an unknown statistic or fewer than two trades.
    """
    if statistic not in SUPPORTED_STATISTICS:
        raise ValueError(f"statistic must be one of {SUPPORTED_STATISTICS}, got {statistic!r}")
    pnls = np.asarray(list(trade_pnls), dtype=float)
    if pnls.size < 2:
        raise ValueError("permutation test needs at least 2 trades")
    if iterations < 1:
        raise ValueError("iterations must be >= 1")

    observed = _path_statistic(pnls, statistic, initial_capital)

    rng = np.random.default_rng(seed)
    null = np.empty(iterations, dtype=float)
    shuffled = pnls.copy()
    for i in range(iterations):
        rng.shuffle(shuffled)
        null[i] = _path_statistic(shuffled, statistic, initial_capital)

    # One-sided, counting the observed value in both numerator and denominator
    # (Davison & Hinkley): a run that was never beaten reports 1/(N+1), not 0.
    at_least_as_good = int(np.sum(null >= observed))
    p_value = (at_least_as_good + 1) / (iterations + 1)

    return PermutationResult(
        statistic=statistic,
        observed=observed,
        p_value=p_value,
        iterations=iterations,
        seed=seed,
        null_mean=float(np.mean(null)),
        null_std=float(np.std(null, ddof=1)) if iterations > 1 else 0.0,
        null_percentiles={
            "p05": float(np.percentile(null, 5)),
            "p50": float(np.percentile(null, 50)),
            "p95": float(np.percentile(null, 95)),
        },
    )


def bootstrap_sharpe_ci(
    returns: Sequence[float],
    *,
    confidence: float = 0.95,
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
    periods_per_year: float = TRADING_DAYS_PER_YEAR,
) -> BootstrapResult:
    """Percentile bootstrap interval around the annualised Sharpe ratio.

    Feed it :func:`quant.backtest.metrics.daily_returns` (or
    ``BacktestResult.daily_returns``). IID resampling with replacement, so it
    captures sampling error in the mean and variance but NOT autocorrelation
    in the returns series -- on a strongly trending series the interval is
    optimistically narrow.

    Raises ``ValueError`` for fewer than two returns or a confidence outside
    ``(0, 1)``.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    rets = np.asarray(list(returns), dtype=float)
    if rets.size < 2:
        raise ValueError("bootstrap needs at least 2 return observations")
    if iterations < 1:
        raise ValueError("iterations must be >= 1")

    observed = sharpe_ratio(rets.tolist(), periods_per_year=periods_per_year)

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, rets.size, size=(iterations, rets.size))
    samples = rets[idx]
    means = samples.mean(axis=1)
    sds = samples.std(axis=1, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        sharpes = np.where(sds > 0, means / sds * np.sqrt(periods_per_year), 0.0)

    tail = (1.0 - confidence) / 2.0
    lower = float(np.percentile(sharpes, tail * 100.0))
    upper = float(np.percentile(sharpes, (1.0 - tail) * 100.0))

    return BootstrapResult(
        observed_sharpe=observed,
        lower=lower,
        upper=upper,
        confidence=confidence,
        iterations=iterations,
        seed=seed,
        standard_error=float(np.std(sharpes, ddof=1)) if iterations > 1 else 0.0,
        prob_positive=float(np.mean(sharpes > 0.0)),
    )
