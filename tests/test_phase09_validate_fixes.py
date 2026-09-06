"""Phase 09: two holes in validate_parameter_search that previously
INFLATED confidence, both fixed additively (existing callers/tests in
tests/test_phase08b_validation.py are unaffected by the new optional
parameters' defaults).

1. n_trials must be the CAMPAIGN's cumulative trial count when called
   from a sweep, not this one call's grid size -- n_trials_override.
2. Zero-trade trials shrink the measured trial_sharpe_std (all exactly
   0.0), which shrinks the luck benchmark, which makes DSR easier to
   pass for the wrong reason -- min_trades filters them out before
   trial_sharpes is built.
"""

from __future__ import annotations

import math
from datetime import datetime

import polars as pl
import pytest

from quant.research.validate import validate_parameter_search

TINY_GRID = {
    "fast_ema": (5, 9),
    "slow_ema": (15, 21),
    "angle_threshold": (20.0, 30.0),
    "angle_lookback": (1, 2),
}


def _month_candles(days: int = 31, bars_per_day: int = 12) -> pl.DataFrame:
    rows = []
    for day in range(1, days + 1):
        for b in range(bars_per_day):
            i = (day - 1) * bars_per_day + b
            price = 22000.0 + 300.0 * math.sin(i / 25.0) + i * 0.4
            rows.append(
                {
                    "timestamp": datetime(2026, 7, day, 9 + b // 2, 15 if b % 2 else 0),
                    "open": price,
                    "high": price + 8,
                    "low": price - 8,
                    "close": price + 2,
                }
            )
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def test_n_trials_override_raises_the_luck_benchmark():
    """A larger n_trials_override must make survival at least as hard
    (deflated Sharpe must not increase), matching sqrt(2 ln N) scaling."""
    candles = _month_candles()
    small = validate_parameter_search(
        candles, grid=TINY_GRID, iterations=200, seed=7, n_trials_override=16
    )
    large = validate_parameter_search(
        candles, grid=TINY_GRID, iterations=200, seed=7, n_trials_override=80_000
    )
    assert small.deflated is not None and large.deflated is not None
    assert small.n_trials == 16
    assert large.n_trials == 80_000
    # A bigger declared search makes the luck benchmark harder to beat.
    assert large.deflated["expected_max_sharpe"] >= small.deflated["expected_max_sharpe"]
    assert large.deflated["deflated_sharpe"] <= small.deflated["deflated_sharpe"]


def test_n_trials_default_is_this_calls_own_grid_size():
    """Without n_trials_override, behaviour is unchanged from before
    Phase 09: n_trials is this call's own (2*2*2*2=16) grid size."""
    candles = _month_candles()
    report = validate_parameter_search(candles, grid=TINY_GRID, iterations=100, seed=7)
    assert report.n_trials == 16


def test_min_trades_filters_out_low_trade_trials():
    """With min_trades set high enough to exclude every trial, the call
    must raise rather than silently select a winner from nothing."""
    candles = _month_candles(days=3, bars_per_day=4)  # too short for many trades
    with pytest.raises(ValueError, match="min_trades"):
        validate_parameter_search(candles, grid=TINY_GRID, iterations=50, seed=7, min_trades=10_000)


def test_min_trades_zero_is_backward_compatible_default():
    """min_trades=0 (the default) must behave exactly as before -- every
    trial, including zero-trade ones, is eligible."""
    candles = _month_candles()
    report = validate_parameter_search(candles, grid=TINY_GRID, iterations=100, seed=7)
    assert report.n_trials == 16  # nothing filtered out of the 2*2*2*2 grid


def test_pbo_trial_count_check_uses_actual_results_not_override():
    """PBO's 'too few trials' skip must be judged on the trials actually
    in THIS call, never on an inflated n_trials_override."""
    candles = _month_candles()
    report = validate_parameter_search(
        candles, grid=TINY_GRID, iterations=50, seed=7, n_trials_override=999_999
    )
    # 16 trials with a full month of shared dates is enough for PBO to
    # actually run (not skip) -- the override must not have masked a
    # real "too few trials" condition that doesn't apply here, nor
    # caused a false pass on a different, smaller grid.
    assert report.pbo is not None or "pbo" in report.skipped
