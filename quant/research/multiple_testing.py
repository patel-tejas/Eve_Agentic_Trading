"""How much of the grid search's edge is search luck? (Phase 08b)

``quant.research.parameter_search`` sweeps a 4-dimensional grid and reports the
combination with the highest net P&L. Under a null where every combination is
worthless, the *maximum* of N draws is comfortably positive, and it grows with
N. Reporting that maximum without saying how many combinations were tried is
the single most common way a research process fools itself.

This module supplies three corrections, in increasing order of what they ask of
the caller:

:func:`probabilistic_sharpe_ratio`
    Confidence that a strategy's true Sharpe exceeds a benchmark, given sample
    length, skew and kurtosis. No trial count involved -- the building block.

:func:`deflated_sharpe_ratio`
    The same statement with the benchmark raised to the Sharpe the *best of N
    trials* would reach by luck alone. Needs the trial count and the spread of
    their Sharpes. This is the number to publish beside any "best parameters"
    claim.

:func:`probability_of_backtest_overfitting`
    CSCV. Needs the full per-trial returns matrix rather than summary
    statistics, and answers a different question: across many in-sample /
    out-of-sample recombinations, how often does the in-sample winner land in
    the bottom half out-of-sample?

Plus :func:`benjamini_hochberg` for controlling the false discovery rate when
screening many candidate strategies at once.

All Sharpe inputs and outputs here are PER-PERIOD, not annualised. Feeding an
annualised Sharpe into these functions inflates every confidence they report;
use ``sharpe_ratio(..., annualised=False)`` from :mod:`quant.research._stats`.

References: Bailey & Lopez de Prado (2012, 2014); Benjamini & Hochberg (1995).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from quant.research._stats import (
    kurtosis,
    norm_cdf,
    norm_ppf,
    sharpe_ratio,
    skewness,
    stdev,
)

# Euler-Mascheroni constant, used by the expected-maximum-of-N-draws formula.
_EULER_GAMMA = 0.5772156649015329


@dataclass(frozen=True)
class DeflatedSharpeResult:
    """Deflated Sharpe ratio and the inputs that produced it."""

    observed_sharpe: float
    deflated_sharpe: float
    expected_max_sharpe: float
    n_trials: int
    n_observations: int
    skew: float
    kurtosis: float
    trial_sharpe_std: float

    @property
    def survives_at_95pct(self) -> bool:
        """True when the edge is still significant after deflation."""
        return self.deflated_sharpe > 0.95

    def to_dict(self) -> dict[str, object]:
        return {
            "observed_sharpe": self.observed_sharpe,
            "deflated_sharpe": self.deflated_sharpe,
            "expected_max_sharpe": self.expected_max_sharpe,
            "n_trials": self.n_trials,
            "n_observations": self.n_observations,
            "skew": self.skew,
            "kurtosis": self.kurtosis,
            "trial_sharpe_std": self.trial_sharpe_std,
            "survives_at_95pct": self.survives_at_95pct,
        }


@dataclass(frozen=True)
class FDRResult:
    """Benjamini-Hochberg false-discovery-rate screen over many p-values."""

    alpha: float
    n_tests: int
    n_rejected: int
    threshold: float
    rejected: list[int] = field(default_factory=list)
    adjusted_p_values: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha": self.alpha,
            "n_tests": self.n_tests,
            "n_rejected": self.n_rejected,
            "threshold": self.threshold,
            "rejected": list(self.rejected),
            "adjusted_p_values": list(self.adjusted_p_values),
        }


@dataclass(frozen=True)
class CSCVResult:
    """Combinatorially symmetric cross-validation overfitting estimate."""

    pbo: float
    n_splits: int
    n_trials: int
    n_partitions: int
    median_oos_rank: float
    logits: list[float] = field(default_factory=list)

    @property
    def overfit(self) -> bool:
        """True when the in-sample winner underperforms out-of-sample more
        often than not."""
        return self.pbo > 0.5

    def to_dict(self) -> dict[str, object]:
        return {
            "pbo": self.pbo,
            "n_splits": self.n_splits,
            "n_trials": self.n_trials,
            "n_partitions": self.n_partitions,
            "median_oos_rank": self.median_oos_rank,
            "overfit": self.overfit,
        }


def probabilistic_sharpe_ratio(
    observed_sharpe: float,
    *,
    n_observations: int,
    benchmark_sharpe: float = 0.0,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """Probability that the true Sharpe exceeds ``benchmark_sharpe``.

    All Sharpes per-period. ``kurt`` is NON-excess (3.0 for a normal
    distribution) -- passing an excess kurtosis here shifts the variance term
    by 3 and silently overstates confidence.

    Negative skew and fat tails both widen the estimator's standard error, so
    a strategy that grinds out small gains and occasionally gives back a large
    one earns less confidence than its point Sharpe suggests.

    Raises ``ValueError`` for fewer than two observations.
    """
    if n_observations < 2:
        raise ValueError("PSR needs at least 2 observations")

    # Standard error of the Sharpe estimator under non-normal returns.
    variance = (1.0 - skew * observed_sharpe + (kurt - 1.0) / 4.0 * observed_sharpe**2) / (
        n_observations - 1
    )
    if variance <= 0.0:
        # A degenerate standard error means the moments are inconsistent with
        # the Sharpe; report a hard verdict rather than a NaN.
        return 1.0 if observed_sharpe > benchmark_sharpe else 0.0
    return norm_cdf((observed_sharpe - benchmark_sharpe) / math.sqrt(variance))


def expected_maximum_sharpe(n_trials: int, trial_sharpe_std: float) -> float:
    """Sharpe the best of ``n_trials`` worthless strategies reaches by luck.

    The expected maximum of N independent standard normals, scaled by the
    observed dispersion of the trials' Sharpes. This is the benchmark that
    :func:`deflated_sharpe_ratio` deflates against: with 320 grid
    combinations whose Sharpes have a spread of 0.5, the best one clears
    roughly 1.5 per-period on noise alone.

    ``n_trials == 1`` gives 0.0 -- with one trial there is no selection to
    correct for.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_trials == 1 or trial_sharpe_std <= 0.0:
        return 0.0

    # Bailey & Lopez de Prado's two-term approximation to E[max of N normals].
    z1 = norm_ppf(1.0 - 1.0 / n_trials)
    z2 = norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    return trial_sharpe_std * ((1.0 - _EULER_GAMMA) * z1 + _EULER_GAMMA * z2)


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    n_trials: int,
    trial_sharpes: Sequence[float] | None = None,
    trial_sharpe_std: float | None = None,
) -> DeflatedSharpeResult:
    """Confidence in the best trial's Sharpe, corrected for the search itself.

    Supply either ``trial_sharpes`` (every trial's per-period Sharpe, from
    which the dispersion is measured) or ``trial_sharpe_std`` directly. When
    both are given, the explicit ``trial_sharpe_std`` wins.

    Reading the result: ``deflated_sharpe`` is a probability. Above 0.95 the
    edge survives the multiplicity correction; near 0.5 the best combination
    is indistinguishable from the luckiest of N coin flips -- which is the
    expected outcome for a grid search over a single month of data.

    Raises ``ValueError`` for fewer than two returns or ``n_trials < 1``.
    """
    rets = list(returns)
    if len(rets) < 2:
        raise ValueError("deflated Sharpe needs at least 2 return observations")
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")

    if trial_sharpe_std is None:
        if trial_sharpes is None:
            raise ValueError("supply either trial_sharpes or trial_sharpe_std")
        trial_sharpe_std = stdev(list(trial_sharpes))

    observed = sharpe_ratio(rets, annualised=False)
    sk = skewness(rets)
    ku = kurtosis(rets)
    benchmark = expected_maximum_sharpe(n_trials, trial_sharpe_std)

    dsr = probabilistic_sharpe_ratio(
        observed,
        n_observations=len(rets),
        benchmark_sharpe=benchmark,
        skew=sk,
        kurt=ku,
    )
    return DeflatedSharpeResult(
        observed_sharpe=observed,
        deflated_sharpe=dsr,
        expected_max_sharpe=benchmark,
        n_trials=n_trials,
        n_observations=len(rets),
        skew=sk,
        kurtosis=ku,
        trial_sharpe_std=trial_sharpe_std,
    )


def benjamini_hochberg(p_values: Sequence[float], *, alpha: float = 0.05) -> FDRResult:
    """Control the false discovery rate across many simultaneous tests.

    Bonferroni controls the chance of *any* false positive and is brutal at
    320 tests. BH instead controls the expected *share* of rejections that are
    false, which is the right target when screening a grid for candidates
    worth a closer look.

    ``rejected`` holds indices into the input order. ``adjusted_p_values`` are
    the step-up adjusted (monotone) values, also in input order.

    Raises ``ValueError`` on an empty input, an out-of-range p-value, or an
    alpha outside ``(0, 1)``.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    p = list(p_values)
    n = len(p)
    if n == 0:
        raise ValueError("benjamini_hochberg needs at least 1 p-value")
    if any(not 0.0 <= x <= 1.0 or math.isnan(x) for x in p):
        raise ValueError("p-values must all lie in [0, 1]")

    order = sorted(range(n), key=lambda i: p[i])
    sorted_p = [p[i] for i in order]

    # Step-up: largest k with p_(k) <= k/n * alpha; reject that and all below.
    threshold = 0.0
    n_rejected = 0
    for k in range(n, 0, -1):
        if sorted_p[k - 1] <= k / n * alpha:
            threshold = k / n * alpha
            n_rejected = k
            break
    rejected = sorted(order[:n_rejected])

    # Adjusted p-values, enforced monotone from the largest downwards.
    adjusted_sorted = [0.0] * n
    running = 1.0
    for k in range(n, 0, -1):
        running = min(running, sorted_p[k - 1] * n / k)
        adjusted_sorted[k - 1] = min(running, 1.0)
    adjusted = [0.0] * n
    for rank, idx in enumerate(order):
        adjusted[idx] = adjusted_sorted[rank]

    return FDRResult(
        alpha=alpha,
        n_tests=n,
        n_rejected=n_rejected,
        threshold=threshold,
        rejected=rejected,
        adjusted_p_values=adjusted,
    )


def probability_of_backtest_overfitting(
    trial_returns: np.ndarray | Sequence[Sequence[float]],
    *,
    n_partitions: int = 8,
) -> CSCVResult:
    """CSCV estimate of how often the in-sample winner fails out-of-sample.

    ``trial_returns`` is an ``(n_observations, n_trials)`` matrix: one column
    per parameter combination, one row per period, aligned on the same
    timeline. The series is cut into ``n_partitions`` equal blocks; every
    balanced half of those blocks in turn serves as in-sample with its
    complement out-of-sample. For each split the in-sample best trial is found
    and its out-of-sample rank recorded.

    PBO is the share of splits where that winner lands in the bottom half
    out-of-sample. Above 0.5 the selection procedure is worse than picking at
    random -- the grid is fitting noise.

    ``n_partitions`` must be even (halves must be balanced) and produces
    ``C(n, n/2)`` splits, so 8 gives 70 and 10 gives 252; beyond that the cost
    climbs fast for little added precision.

    Raises ``ValueError`` for an odd ``n_partitions``, fewer than two trials,
    or too few observations to partition.
    """
    if n_partitions % 2 != 0 or n_partitions < 2:
        raise ValueError(f"n_partitions must be a positive even number, got {n_partitions}")

    matrix = np.asarray(trial_returns, dtype=float)
    if matrix.ndim != 2:
        raise ValueError("trial_returns must be 2-D (observations x trials)")
    n_obs, n_trials = matrix.shape
    if n_trials < 2:
        raise ValueError("PBO needs at least 2 trials to rank")
    if n_obs < n_partitions:
        raise ValueError(f"need at least {n_partitions} observations, got {n_obs}")

    # Equal blocks; a remainder at the tail is dropped so every split is
    # balanced in length as well as in block count.
    block_len = n_obs // n_partitions
    blocks = [matrix[i * block_len : (i + 1) * block_len, :] for i in range(n_partitions)]

    from itertools import combinations

    half = n_partitions // 2
    logits: list[float] = []
    oos_ranks: list[float] = []

    for is_idx in combinations(range(n_partitions), half):
        oos_idx = [i for i in range(n_partitions) if i not in is_idx]
        is_data = np.vstack([blocks[i] for i in is_idx])
        oos_data = np.vstack([blocks[i] for i in oos_idx])

        is_perf = _column_sharpes(is_data)
        oos_perf = _column_sharpes(oos_data)

        best = int(np.argmax(is_perf))
        # Relative rank of the in-sample winner within the OOS results:
        # 1.0 = best out-of-sample, near 0 = worst.
        rank = float(np.sum(oos_perf <= oos_perf[best])) / n_trials
        oos_ranks.append(rank)

        # Clipped so a winner that ranks first or last stays finite.
        clipped = min(max(rank, 1.0 / (n_trials + 1)), 1.0 - 1.0 / (n_trials + 1))
        logits.append(math.log(clipped / (1.0 - clipped)))

    pbo = float(np.mean([1.0 if x <= 0.0 else 0.0 for x in logits]))

    return CSCVResult(
        pbo=pbo,
        n_splits=len(logits),
        n_trials=n_trials,
        n_partitions=n_partitions,
        median_oos_rank=float(np.median(oos_ranks)),
        logits=logits,
    )


def _column_sharpes(data: np.ndarray) -> np.ndarray:
    """Per-period Sharpe of each column; zero where the column is flat."""
    means = data.mean(axis=0)
    sds = data.std(axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sds > 0, means / sds, 0.0)
