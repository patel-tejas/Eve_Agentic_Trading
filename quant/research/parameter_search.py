"""Parameter grid search (Phase 08).

Sweep fast/slow EMA periods, angle threshold and angle lookback over a
TRAINING window only, so untouched validation/test windows stay clean.
Every configuration is run through the real Phase 04 signal engine and
Phase 05 backtester; results are a deterministic frame sorted by net P&L.

Windows are half-open ``[start, end)`` so day slices align cleanly.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timedelta

import polars as pl

from quant.backtest.engine import BacktestConfig, run_backtest
from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

DEFAULT_GRID: dict[str, tuple[int | float, ...]] = {
    "fast_ema": (5, 7, 9, 12),
    "slow_ema": (15, 18, 21, 25),
    "angle_threshold": (20.0, 25.0, 30.0, 35.0, 40.0),
    "angle_lookback": (1, 2, 3, 5),
}

GRID_METRICS = (
    "net_pnl",
    "gross_pnl",
    "profit_factor",
    "win_rate",
    "total_trades",
    "max_drawdown_pct",
    "sharpe",
    "sortino",
    "avg_trade_pnl",
)


@dataclass(frozen=True)
class GridResult:
    """Outcome of one parameter combination on a calendar window."""

    params: dict[str, int | float]
    metrics: dict[str, float | int | str]

    def to_row(self, experiment_id: str) -> dict[str, object]:
        return {
            "experiment_id": experiment_id,
            **self.params,
            **{key: self.metrics.get(key) for key in GRID_METRICS},
        }


def grid_combinations(
    grid: dict[str, tuple[int | float, ...]] | None = None,
) -> list[dict[str, int | float]]:
    """Cartesian product of the search grid, keeping only valid configs."""
    grid = grid or DEFAULT_GRID
    names = list(grid.keys())
    combos = [dict(zip(names, v)) for v in itertools.product(*(grid[n] for n in names))]
    return [c for c in combos if c["fast_ema"] < c["slow_ema"]]


def evaluate_params(
    candles: pl.DataFrame,
    params: dict[str, int | float],
    *,
    window: tuple[datetime, datetime] | None = None,
    backtest_config: BacktestConfig | None = None,
) -> GridResult:
    """Signals + backtest for one parameter set, optionally inside a window.

    ``window`` is half-open: bars with ``start <= timestamp < end``.
    """
    frame = candles
    if window is not None:
        start, end = window
        frame = candles.filter(
            (pl.col("timestamp") >= start) & (pl.col("timestamp") < end)
        )
        if frame.height == 0:
            raise ValueError(f"no bars in window [{start}, {end})")
    cfg = StrategyConfig(**params)
    signals = generate_signals(frame, config=cfg)
    result = run_backtest(frame, signals, backtest_config or BacktestConfig())
    return GridResult(params=params, metrics=result.metrics)


def parameter_grid_search(
    candles: pl.DataFrame,
    *,
    window: tuple[datetime, datetime] | None = None,
    grid: dict[str, tuple[int | float, ...]] | None = None,
    backtest_config: BacktestConfig | None = None,
) -> pl.DataFrame:
    """Sweep the grid on ``window``; results sorted by net P&L descending."""
    combos = grid_combinations(grid)
    rows = [
        evaluate_params(
            candles, params, window=window, backtest_config=backtest_config
        ).to_row(f"RE-{i:04d}")
        for i, params in enumerate(combos, start=1)
    ]
    results = pl.DataFrame(rows)
    return results.sort("net_pnl", descending=True)


def split_schedule(
    candles: pl.DataFrame,
    *,
    train_days: int = 23,
    validation_days: int = 4,
    test_days: int = 4,
) -> dict[str, tuple[datetime, datetime]]:
    """Train/validation/test calendar windows (half-open, sequential).

    Defaults match the phase-08 spec for July 2026: train 1-23,
    validation 24-27, test 28-31.
    """
    first = candles["timestamp"].min()
    start = datetime(first.year, first.month, first.day)
    train = (start, start + timedelta(days=train_days))
    validation = (train[1], train[1] + timedelta(days=validation_days))
    test = (validation[1], validation[1] + timedelta(days=test_days))
    return {"train": train, "validation": validation, "test": test}
