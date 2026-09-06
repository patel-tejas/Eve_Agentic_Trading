"""One call that runs a parameter search AND says whether to believe it.

``quant.research.parameter_search`` answers "which parameters scored best".
This module answers the question that has to follow it: *given that we tried
this many combinations, is the winner distinguishable from the luckiest of N
coin flips?*

:func:`validate_parameter_search` runs the grid, then applies all four phase-08b
tests to the winner and to the search as a whole:

===========================  =======================================
Deflated Sharpe              is the winner's Sharpe beyond what the
                             best of N trials reaches by luck?
Bootstrap Sharpe CI          how wide is the uncertainty around it?
Permutation test             was the equity path's shape luckier than
                             a random ordering of the same trades?
PBO (CSCV)                   does the selection procedure itself
                             generalise, or is it fitting noise?
===========================  =======================================

WHY THIS WRAPPER EXISTS
-----------------------
The wiring is easy to get wrong in a way that silently inflates confidence:

* ``parameter_grid_search`` reports an ANNUALISED Sharpe in its ``sharpe``
  column, while :func:`~quant.research.multiple_testing.deflated_sharpe_ratio`
  is defined on PER-PERIOD Sharpes. Feeding the former into the latter
  overstates every trial's dispersion by sqrt(252) and the deflation becomes
  meaningless. This module derives per-period Sharpes from each trial's own
  daily returns instead of reading that column.
* trials warm up over different numbers of bars, so their return series have
  different lengths. They are aligned on shared dates here, never stacked
  positionally.
* ``n_trials`` must be the number of combinations actually evaluated, not the
  size of the declared grid -- ``grid_combinations`` drops the invalid
  ``fast >= slow`` pairs.

KNOWN ASYMMETRY
---------------
CSCV ranks trials internally by Sharpe, while ``select_by`` defaults to
``net_pnl``. So the PBO figure answers "does selecting on Sharpe generalise?"
while the deflated Sharpe deflates a winner chosen on net P&L. On this grid the
two orderings usually agree, but they are not the same question, and PBO should
be read as evidence about the search procedure rather than about this specific
winner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import polars as pl

from quant.backtest.engine import BacktestConfig
from quant.research._stats import sharpe_ratio
from quant.research.multiple_testing import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
)
from quant.research.parameter_search import GridResult, evaluate_params, grid_combinations
from quant.research.significance import (
    DEFAULT_ITERATIONS,
    DEFAULT_SEED,
    bootstrap_sharpe_ci,
    monte_carlo_permutation_test,
)

# CSCV needs enough shared days to cut into balanced blocks, and enough trials
# to rank meaningfully; below either threshold it is skipped with a reason
# rather than reported as a number nobody should act on.
MIN_PBO_TRIALS = 2
MIN_PBO_OBSERVATIONS = 8


@dataclass(frozen=True)
class SearchValidation:
    """Every phase-08b verdict for one parameter search."""

    n_trials: int
    best_params: dict[str, int | float]
    best_metrics: dict[str, float | int | str]
    deflated: dict[str, Any] | None = None
    bootstrap: dict[str, Any] | None = None
    permutation: dict[str, Any] | None = None
    pbo: dict[str, Any] | None = None
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def credible(self) -> bool:
        """True only when all three EDGE tests that ran came back favourable.

        The three gating tests are the deflated Sharpe (must survive at 95%),
        the bootstrap interval (must exclude zero) and PBO (must not be
        overfit).

        The permutation test is deliberately NOT a gate. As
        :mod:`quant.research.significance` says of it, it "says nothing about
        whether the average trade is profitable, and everything about whether
        the *path* was luckier than a coin-flip ordering" -- it describes the
        shape of the equity curve, and a strategy with a genuine edge whose
        losses happened to cluster is not thereby uncredible. Read its
        p-value alongside this flag, not through it.

        Conservative by construction: a test that could not run does NOT
        count as a pass, so a search too small to validate is never reported
        as credible.
        """
        if not self.deflated or self.skipped:
            return False
        if not self.deflated.get("survives_at_95pct"):
            return False
        if self.bootstrap and not self.bootstrap.get("excludes_zero"):
            return False
        if self.pbo and self.pbo.get("overfit"):
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_trials": self.n_trials,
            "best_params": dict(self.best_params),
            "best_metrics": dict(self.best_metrics),
            "deflated_sharpe": self.deflated,
            "bootstrap": self.bootstrap,
            "permutation": self.permutation,
            "pbo": self.pbo,
            "skipped": dict(self.skipped),
            "credible": self.credible,
        }

    def summary_lines(self) -> list[str]:
        """Short human-readable verdict, for a report or a run card note."""
        lines = [f"Trials evaluated: {self.n_trials}", f"Best params: {self.best_params}"]
        if self.deflated:
            lines.append(
                f"Deflated Sharpe: {self.deflated['deflated_sharpe']:.4f} "
                f"(observed per-period {self.deflated['observed_sharpe']:.4f} vs "
                f"luck benchmark {self.deflated['expected_max_sharpe']:.4f}) -> "
                f"{'SURVIVES' if self.deflated['survives_at_95pct'] else 'DOES NOT SURVIVE'}"
            )
        if self.bootstrap:
            lines.append(
                f"Sharpe 95% CI: [{self.bootstrap['ci_lower']:.2f}, "
                f"{self.bootstrap['ci_upper']:.2f}] -> "
                f"{'excludes' if self.bootstrap['excludes_zero'] else 'includes'} zero"
            )
        if self.permutation:
            lines.append(
                f"Permutation ({self.permutation['statistic']}), informational: "
                f"p = {self.permutation['p_value']:.4f} "
                f"(path shape only; does not gate the verdict)"
            )
        if self.pbo:
            lines.append(
                f"PBO: {self.pbo['pbo']:.3f} over {self.pbo['n_splits']} splits -> "
                f"{'OVERFIT' if self.pbo['overfit'] else 'acceptable'}"
            )
        for name, reason in sorted(self.skipped.items()):
            lines.append(f"Skipped {name}: {reason}")
        lines.append(f"VERDICT: {'credible' if self.credible else 'not established'}")
        return lines


def _aligned_matrix(results: list[GridResult]) -> tuple[np.ndarray, list[object]]:
    """Stack trial returns on the dates every trial shares.

    Returns ``(matrix, dates)`` where ``matrix`` is (n_dates, n_trials).
    """
    if not results:
        return np.empty((0, 0)), []
    shared: set[object] | None = None
    for res in results:
        keys = set(res.returns_by_date)
        shared = keys if shared is None else (shared & keys)
    dates = sorted(shared or [], key=str)
    if not dates:
        return np.empty((0, len(results))), []
    matrix = np.array([[res.returns_by_date[d] for res in results] for d in dates], dtype=float)
    return matrix, dates


def validate_parameter_search(
    candles: pl.DataFrame,
    *,
    window: tuple[datetime, datetime] | None = None,
    grid: dict[str, tuple[int | float, ...]] | None = None,
    backtest_config: BacktestConfig | None = None,
    select_by: str = "net_pnl",
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = DEFAULT_SEED,
    n_partitions: int = 8,
    min_trades: int = 0,
    n_trials_override: int | None = None,
) -> SearchValidation:
    """Run the grid on ``window`` and validate the winner against the search.

    ``select_by`` names the metric the winner is chosen on and defaults to
    ``net_pnl``, matching what :func:`parameter_grid_search` sorts by -- the
    correction is only honest if it deflates the same selection rule the
    research process actually used.

    Tests that cannot run on the available data are recorded in ``skipped``
    with a reason rather than silently omitted, and any skip makes
    :attr:`SearchValidation.credible` False.

    Phase 09 -- two holes fixed, both of which previously INFLATED
    confidence:

    ``min_trades`` filters out zero/near-zero-trade trials BEFORE
    selection and BEFORE ``trial_sharpes`` is built. A zero-trade trial
    has no return variance, so ``sharpe_ratio`` reports exactly 0.0; a
    pile of identical 0.0s SHRINKS the measured dispersion across
    trials (``trial_sharpe_std``), which shrinks the expected-maximum-
    Sharpe luck benchmark, which makes the deflated Sharpe ratio easier
    to pass for the WRONG reason. The existing walk-forward step
    schedule already produces zero-trade steps, so this is not a
    hypothetical.

    ``n_trials_override``, when given, is what
    :func:`quant.research.multiple_testing.deflated_sharpe_ratio` is
    penalized against, INSTEAD of ``len(results)`` (this call's own grid
    size). A sweep campaign runs many rounds; passing this round's count
    when the CAMPAIGN tried far more (see
    ``quant.research.leaderboard.cumulative_trial_count``) understates
    the luck benchmark and again inflates confidence. Leave unset for a
    single stand-alone grid search, where this call's own trial count
    is the correct (and only) number.
    """
    cfg = backtest_config or BacktestConfig()
    combos = grid_combinations(grid)
    if not combos:
        raise ValueError("grid produced no valid combinations")

    all_results = [
        evaluate_params(candles, params, window=window, backtest_config=cfg) for params in combos
    ]
    results = [r for r in all_results if int(r.metrics.get("total_trades", 0)) >= min_trades]
    if not results:
        raise ValueError(
            f"no trial cleared min_trades={min_trades} (out of {len(all_results)} evaluated); "
            "cannot select a winner from an empty candidate set"
        )
    n_trials = n_trials_override if n_trials_override is not None else len(results)

    # Without this guard a typo'd metric name would score every trial 0.0,
    # make ``max`` return the first combination, and report a confident
    # verdict about a winner nothing actually selected.
    if select_by not in results[0].metrics:
        raise ValueError(
            f"select_by={select_by!r} is not a computed metric; "
            f"available: {sorted(results[0].metrics)}"
        )

    best_idx = max(range(len(results)), key=lambda i: float(results[i].metrics[select_by]))
    best = results[best_idx]
    best_returns = [best.returns_by_date[d] for d in sorted(best.returns_by_date, key=str)]

    skipped: dict[str, str] = {}
    deflated = bootstrap = permutation = pbo = None

    # Per-period Sharpes, derived from each SURVIVING trial's own returns
    # (post min_trades filter) -- NOT the annualised `sharpe` metric
    # column. See the module docstring and the min_trades note above.
    trial_sharpes = [
        sharpe_ratio(
            [r.returns_by_date[d] for d in sorted(r.returns_by_date, key=str)],
            annualised=False,
        )
        for r in results
    ]

    if len(best_returns) >= 2:
        deflated = deflated_sharpe_ratio(
            best_returns, n_trials=n_trials, trial_sharpes=trial_sharpes
        ).to_dict()
        bootstrap = bootstrap_sharpe_ci(best_returns, iterations=iterations, seed=seed).to_dict()
    else:
        reason = f"winner has {len(best_returns)} daily returns, need >= 2"
        skipped["deflated_sharpe"] = reason
        skipped["bootstrap"] = reason

    if len(best.trade_pnls) >= 2:
        permutation = monte_carlo_permutation_test(
            best.trade_pnls,
            iterations=iterations,
            seed=seed,
            initial_capital=cfg.initial_capital,
        ).to_dict()
    else:
        skipped["permutation"] = f"winner made {len(best.trade_pnls)} trades, need >= 2"

    matrix, _ = _aligned_matrix(results)
    # PBO's CSCV runs over `matrix`, whose width is len(results) -- the
    # trials ACTUALLY IN THIS CALL, never the (possibly campaign-wide,
    # much larger) n_trials_override. Gating this check on the override
    # would let a tiny/degenerate `results` skip the "too few trials"
    # check it should trigger.
    if len(results) < MIN_PBO_TRIALS:
        skipped["pbo"] = f"{len(results)} trial(s), need >= {MIN_PBO_TRIALS}"
    elif matrix.shape[0] < max(n_partitions, MIN_PBO_OBSERVATIONS):
        skipped["pbo"] = (
            f"{matrix.shape[0]} shared dates across trials, "
            f"need >= {max(n_partitions, MIN_PBO_OBSERVATIONS)}"
        )
    else:
        pbo = probability_of_backtest_overfitting(matrix, n_partitions=n_partitions).to_dict()

    return SearchValidation(
        n_trials=n_trials,
        best_params=dict(best.params),
        best_metrics=dict(best.metrics),
        deflated=deflated,
        bootstrap=bootstrap,
        permutation=permutation,
        pbo=pbo,
        skipped=skipped,
    )
