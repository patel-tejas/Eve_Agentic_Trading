"""Walk-forward validation (Phase 08).

Each step calibrates parameters on its TRAINING window (via grid search,
picking best net P&L) and evaluates them on an untouched TEST window; the
test result is an out-of-sample observation. Training is anchored at the
first day and grows by ``test_days`` per step.

Default schedule for a 31-day month (matches the phase-08 spec):
    Step 1: train 1-15  -> test 16-20
    Step 2: train 1-20  -> test 21-25
    Step 3: train 1-25  -> test 26-31

Windows are half-open ``[start, end)``.

EMBARGO (phase 08b)
-------------------
Between ``train_end`` and ``test_start`` sits an embargo of
``DEFAULT_EMBARGO_DAYS`` calendar days that belongs to neither window. Without
it a position opened near the end of the training window is still open when the
test window starts, so the same bars inform both the parameter choice and the
score that choice is judged by -- the test result is then not out-of-sample.

The default of 1 day preserves the schedule this module has always produced
(``test_start`` was already ``train_end + 1 day``); it is now a named,
documented parameter rather than an accident of the arithmetic. Raise it above
the strategy's maximum holding period if that ever exceeds a single session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import polars as pl

from quant.backtest.engine import BacktestConfig
from quant.research.parameter_search import evaluate_params, parameter_grid_search

TEST_WINDOW_DAYS = 5
DEFAULT_EMBARGO_DAYS = 1

_PARAM_COLUMNS = {"fast_ema", "slow_ema", "angle_threshold", "angle_lookback"}


@dataclass(frozen=True)
class WalkForwardStep:
    """One walk-forward step: calibration window + unseen test window."""

    step: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    best_params: dict[str, int | float]
    train_net_pnl: float
    test_net_pnl: float
    test_trades: int
    test_profit_factor: float
    embargo_days: int = DEFAULT_EMBARGO_DAYS

    def to_row(self) -> dict[str, object]:
        return {
            "step": self.step,
            "train_start": self.train_start,
            "train_end": self.train_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            **self.best_params,
            "train_net_pnl": self.train_net_pnl,
            "test_net_pnl": self.test_net_pnl,
            "test_trades": self.test_trades,
            "test_profit_factor": self.test_profit_factor,
            "embargo_days": self.embargo_days,
        }


def define_walk_windows(
    first_day: datetime,
    last_day: datetime,
    *,
    test_days: int = TEST_WINDOW_DAYS,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
) -> list[tuple[datetime, datetime, datetime, datetime]]:
    """(train_start, train_end, test_start, test_end) sequences, half-open.

    ``embargo_days`` calendar days are dropped between each training window's
    end and its test window's start, so no trade that was open while the
    parameters were being fitted can still be open when they are scored. See
    the module docstring for why the default is 1.
    """
    if embargo_days < 0:
        raise ValueError(f"embargo_days must be >= 0, got {embargo_days}")
    windows: list[tuple[datetime, datetime, datetime, datetime]] = []
    train_end = first_day + timedelta(days=14)
    while train_end + timedelta(days=test_days) <= last_day:
        test_start = train_end + timedelta(days=embargo_days)
        test_end = min(
            test_start + timedelta(days=test_days), last_day + timedelta(days=1)
        )
        if test_start < test_end:
            windows.append((first_day, train_end, test_start, test_end))
        train_end += timedelta(days=test_days)
    return windows


def walk_forward(
    candles: pl.DataFrame,
    *,
    grid: dict[str, tuple[int | float, ...]] | None = None,
    backtest_config: BacktestConfig | None = None,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
) -> list[WalkForwardStep]:
    """Run all walk-forward steps on ``candles``; one record per step.

    ``embargo_days`` is forwarded to :func:`define_walk_windows` and recorded
    on every step, so a report can state the gap it was scored under instead
    of leaving the reader to infer it from the window dates.
    """
    cfg = backtest_config or BacktestConfig()
    ts = candles["timestamp"]
    first_day = datetime(ts.min().year, ts.min().month, ts.min().day)
    last_day = datetime(ts.max().year, ts.max().month, ts.max().day)

    windows = define_walk_windows(first_day, last_day, embargo_days=embargo_days)
    if not windows:
        raise ValueError("dataset too short for a walk-forward split")

    steps: list[WalkForwardStep] = []
    for i, (train_start, train_end, test_start, test_end) in enumerate(windows, start=1):
        best, train_net = _calibrate(candles, (train_start, train_end), grid, cfg)
        test_result = evaluate_params(
            candles,
            best,
            window=(test_start, test_end),
            backtest_config=cfg,
        )
        tm = test_result.metrics
        steps.append(
            WalkForwardStep(
                step=i,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                best_params=best,
                train_net_pnl=train_net,
                test_net_pnl=float(tm["net_pnl"]),
                test_trades=int(tm["total_trades"]),
                test_profit_factor=float(tm["profit_factor"]),
                embargo_days=embargo_days,
            )
        )
    return steps


def _calibrate(
    candles: pl.DataFrame,
    window: tuple[datetime, datetime],
    grid: dict[str, tuple[int | float, ...]] | None,
    cfg: BacktestConfig,
) -> tuple[dict[str, int | float], float]:
    """Grid-search the training window; return (best params, train net P&L)."""
    start, end = window
    train = candles.filter(
        (pl.col("timestamp") >= start) & (pl.col("timestamp") < end)
    )
    results = parameter_grid_search(train, backtest_config=cfg, grid=grid)
    best = results.head(1).to_dicts()[0]
    params = {name: best[name] for name in _PARAM_COLUMNS}
    return params, float(best["net_pnl"])
