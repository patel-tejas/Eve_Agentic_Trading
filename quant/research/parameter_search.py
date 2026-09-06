"""Parameter grid search (Phase 08).

Sweep fast/slow EMA periods, angle threshold and angle lookback over a
TRAINING window only, so untouched validation/test windows stay clean.
Every configuration is run through the real Phase 04 signal engine and
Phase 05 backtester; results are a deterministic frame sorted by net P&L.

Windows are half-open ``[start, end)`` so day slices align cleanly.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta

import polars as pl

from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.exits import ExitConfig
from quant.backtest.metrics import daily_returns_by_date
from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

DEFAULT_GRID: dict[str, tuple[int | float, ...]] = {
    "fast_ema": (5, 7, 9, 12),
    "slow_ema": (15, 18, 21, 25),
    "angle_threshold": (20.0, 25.0, 30.0, 35.0, 40.0),
    "angle_lookback": (1, 2, 3, 5),
}

# Phase 09: the new tuning space. DEFAULT_GRID above is FROZEN (its 320
# combinations are asserted by tests/test_phase08_research.py) -- these
# are separate constants, not a replacement.
#
# STAGE1_EMA_GRID -- entry logic, full cartesian (cheap, ~575 valid
# combos after canonical de-dup via quant.research.sampling). Keeps
# fast_ema=9/slow_ema=15 so the incumbent is ranked inside its own grid,
# and adds ATR-normalized slope gating (see quant.indicators.angle) as
# the only mode swept -- the fixed-scale formula's selectivity varies
# 131x across timeframe/lookback and is not worth re-searching.
STAGE1_EMA_GRID: dict[str, tuple[object, ...]] = {
    "fast_ema": (5, 8, 9, 13, 21),
    "slow_ema": (15, 21, 34, 55, 89),
    "angle_mode": ("atr_normalized",),
    "slope_threshold_atr": (0.0, 0.10, 0.20, 0.30, 0.45),
    "angle_lookback": (1, 3, 5),
    "signal_mode": ("crossover_and_angle", "crossover_angle_and_trend"),
}

# STAGE2_EXIT_GRID -- bracket exits, LHS-sampled (full cartesian is 7,680;
# top-K stage-1 winners x LHS(n=128) = 768 trials instead). Needs
# quant.backtest.exits.ExitConfig fields, not StrategyConfig fields --
# callers combine a Stage 1 params dict with one of these separately.
STAGE2_EXIT_GRID: dict[str, tuple[object, ...]] = {
    "stop_mode": ("atr",),
    "stop_atr_mult": (0.75, 1.0, 1.5, 2.0, 3.0),
    "target_mode": ("none", "r_multiple"),
    "target_r_multiple": (1.0, 1.5, 2.0, 3.0),
    "trail_mode": ("none", "atr", "breakeven_then_atr"),
    "trail_atr_mult": (1.5, 2.5),
    "time_stop_bars": (0, 12, 30, 75),
    "session_start": ("09:15", "09:30"),
    "session_end": ("14:45", "15:10"),
    "eod_squareoff": ("15:15",),  # 15:15, not 15:20 -- see exits.py docstring
}

# Stage 3 (local refinement) varies only these numeric axes of
# STAGE2_EXIT_GRID -- "+/-1 grid step on the numeric axes around the
# Stage-2 winner", per the implementation plan. Pass THIS to
# quant.research.sampling.local_refinement, not the full
# STAGE2_EXIT_GRID: the categorical fields (stop_mode, target_mode,
# trail_mode, session_start/end, eod_squareoff) stay fixed at the
# Stage-2 winner's values, giving <= 3**4 = 81 combos (fewer once edge
# values clip), not the 3**8-ish blow-up varying every field would cause.
STAGE3_NUMERIC_AXES: dict[str, tuple[object, ...]] = {
    "stop_atr_mult": STAGE2_EXIT_GRID["stop_atr_mult"],
    "target_r_multiple": STAGE2_EXIT_GRID["target_r_multiple"],
    "trail_atr_mult": STAGE2_EXIT_GRID["trail_atr_mult"],
    "time_stop_bars": STAGE2_EXIT_GRID["time_stop_bars"],
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
    # Date-keyed so trials with different EMA warm-ups can still be aligned;
    # deliberately absent from ``to_row`` -- the parquet grid stays scalar.
    returns_by_date: dict[object, float] = dataclass_field(default_factory=dict)
    trade_pnls: list[float] = dataclass_field(default_factory=list)

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
    exit_params: dict[str, object] | None = None,
) -> GridResult:
    """Signals + backtest for one parameter set, optionally inside a window.

    ``window`` is half-open: bars with ``start <= timestamp < end``.

    ``exit_params`` (Phase 09) -- an ``ExitConfig`` field dict (Stage 2 of
    the staged search) -- is layered onto ``backtest_config`` via
    ``dataclasses.replace``, so ``backtest_config``'s ``market``/``costs``/
    ``execution`` are preserved and only ``exits`` changes. The recorded
    ``GridResult.params`` includes both so a leaderboard row is
    self-describing without needing the caller's grid definitions.
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

    bt_cfg = backtest_config or BacktestConfig()
    recorded_params = dict(params)
    if exit_params is not None:
        bt_cfg = replace(bt_cfg, exits=ExitConfig(**exit_params))
        recorded_params = {**recorded_params, **exit_params}

    result = run_backtest(frame, signals, bt_cfg)
    return GridResult(
        params=recorded_params,
        metrics=result.metrics,
        returns_by_date=daily_returns_by_date(result.equity),
        trade_pnls=result.trades["net_pnl"].to_list(),
    )


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
