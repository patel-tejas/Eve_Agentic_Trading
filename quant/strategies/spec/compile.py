"""Compile an ``eve.strategy/1`` spec into engine inputs (Phase 15).

``spec_signals(candles, spec)`` -> the standard signal frame
(``timestamp, signal_type, stop_price, target_price``) every registered
strategy returns. ``spec_backtest_config(spec)`` -> the ``BacktestConfig``
whose ``ExitConfig`` carries the spec's risk and session blocks.

Causality: every operand is a backward-looking Polars expression; offsets are
``shift(+n)`` only (the schema forbids negative offsets); crossovers compare
bar ``t`` with ``t-1``. Signals are decided at the bar's close and the engine
fills them at the next bar's open. ``tests/test_phase15_compile_causality.py``
truncates the future and checks no earlier signal changes.

Signal mapping per bar, with ``le/se`` = long/short entry and ``lx/sx`` =
long/short exit conditions:

1. ``le`` and ``se`` together are contradictory: both are ignored.
2. ``lx`` and ``sx`` together -> ``EXIT`` (flatten whatever is open).
3. ``lx`` -> ``SELL`` if ``se`` (closes a long; opens a short from flat),
   else ``EXIT_LONG`` (closes a long, never opens anything).
4. ``sx`` -> ``BUY`` if ``le``, else ``EXIT_SHORT``.
5. ``le`` -> ``BUY``; ``se`` -> ``SELL``.

An entry in one direction closes an open position in the other (the
engine's long-standing "opposite signal exits" rule), and an exit on the same
bar as a same-direction entry wins -- a contradictory bar does nothing.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from quant.backtest.costs import CostConfig, SlippageConfig
from quant.backtest.engine import BacktestConfig
from quant.backtest.execution import ExecutionConfig
from quant.backtest.exits import ExitConfig
from quant.indicators.structure import add_prev_day_levels, add_vwap
from quant.strategies._common import SIGNAL_SCHEMA
from quant.strategies.spec.schema import (
    ChangePctOperand,
    Condition,
    ConditionGroup,
    ConstOperand,
    IndicatorOperand,
    LevelOperand,
    PriceOperand,
    StrategySpecV1,
)
from quant.strategies.spec.vocabulary import INDICATORS

# NSE NIFTY index-derivative lot size, revised from 75 to 65 for contracts
# from the January 2026 expiries. Treated as data: change it here, and the
# spec and every result card report which value was used.
NIFTY_LOT_SIZE = 65


def _day() -> pl.Expr:
    return pl.col("timestamp").dt.date()


def _base_frame(candles: pl.DataFrame, spec: StrategySpecV1) -> pl.DataFrame:
    frame = candles.sort("timestamp")
    needed = {"timestamp", "open", "high", "low", "close"}
    missing = needed - set(frame.columns)
    if missing:
        raise ValueError(f"candles are missing columns {sorted(missing)}")
    if "volume" not in frame.columns:
        frame = frame.with_columns(pl.lit(0.0).alias("volume"))
    uses = _operand_kinds(spec)
    if uses & {"prev_day_high", "prev_day_low", "prev_day_close"}:
        frame = add_prev_day_levels(frame)
    if "vwap" in uses:
        frame = add_vwap(frame)
    return frame


def _operand_kinds(spec: StrategySpecV1) -> set[str]:
    kinds: set[str] = set()
    for group in _groups(spec):
        for cond in group.all + group.any:
            for op in (cond.lhs, cond.rhs):
                if isinstance(op, LevelOperand):
                    kinds.add(op.name)
                elif isinstance(op, ChangePctOperand) and op.ref == "prev_day_close":
                    kinds.add("prev_day_close")
    return kinds


def _groups(spec: StrategySpecV1) -> list[ConditionGroup]:
    out = []
    for rules in (spec.entry, spec.exit):
        for side in ("long", "short"):
            group = getattr(rules, side)
            if group is not None:
                out.append(group)
    return out


_LEVEL_EXPR = {
    "prev_day_high": lambda: pl.col("pdh"),
    "prev_day_low": lambda: pl.col("pdl"),
    "prev_day_close": lambda: pl.col("pdc"),
    "session_open": lambda: pl.col("open").first().over(_day()),
    "session_high": lambda: pl.col("high").cum_max().over(_day()),
    "session_low": lambda: pl.col("low").cum_min().over(_day()),
    "vwap": lambda: pl.col("vwap"),
}


def operand_expr(op: Any) -> pl.Expr:
    if isinstance(op, ConstOperand):
        return pl.lit(float(op.value))
    if isinstance(op, IndicatorOperand):
        definition = INDICATORS[op.name]
        expr = definition.compute(definition.resolved_params(op.params), op.output)
    elif isinstance(op, PriceOperand):
        expr = pl.col(op.field).cast(pl.Float64)
    elif isinstance(op, LevelOperand):
        expr = _LEVEL_EXPR[op.name]()
    elif isinstance(op, ChangePctOperand):
        ref = {
            "prev_day_close": pl.col("pdc"),
            "session_open": pl.col("open").first().over(_day()),
            "prev_bar_close": pl.col("close").shift(1),
        }[op.ref]
        expr = (pl.col("close") - ref) / ref * 100.0
    else:  # pragma: no cover - the schema's discriminator is closed
        raise TypeError(f"unknown operand {op!r}")
    return expr.shift(op.offset) if op.offset else expr


def condition_expr(cond: Condition) -> pl.Expr:
    lhs = operand_expr(cond.lhs)
    if cond.cmp in ("rising", "falling"):
        past = lhs.shift(cond.bars or 1)
        out = lhs > past if cond.cmp == "rising" else lhs < past
        return out.fill_null(False)
    rhs = operand_expr(cond.rhs)
    if cond.cmp == "gt":
        out = lhs > rhs
    elif cond.cmp == "gte":
        out = lhs >= rhs
    elif cond.cmp == "lt":
        out = lhs < rhs
    elif cond.cmp == "lte":
        out = lhs <= rhs
    elif cond.cmp == "crosses_above":
        # Same definition as the registered EMA strategy's crossover.
        out = (lhs > rhs) & (lhs.shift(1) <= rhs.shift(1))
    else:  # crosses_below
        out = (lhs < rhs) & (lhs.shift(1) >= rhs.shift(1))
    return out.fill_null(False)


def group_expr(group: ConditionGroup | None) -> pl.Expr:
    if group is None or group.empty:
        return pl.lit(False)
    all_ok = pl.lit(True)
    for cond in group.all:
        all_ok = all_ok & condition_expr(cond)
    any_ok = pl.lit(True)
    if group.any:
        any_ok = pl.lit(False)
        for cond in group.any:
            any_ok = any_ok | condition_expr(cond)
    return all_ok & any_ok


def spec_condition_frame(candles: pl.DataFrame, spec: StrategySpecV1) -> pl.DataFrame:
    """Per-bar entry/exit booleans (``le, se, lx, sx``) -- useful for previews."""
    frame = _base_frame(candles, spec)
    return frame.with_columns(
        group_expr(spec.entry.long).alias("le"),
        group_expr(spec.entry.short).alias("se"),
        group_expr(spec.exit.long).alias("lx"),
        group_expr(spec.exit.short).alias("sx"),
    )


def spec_signals(candles: pl.DataFrame, spec: StrategySpecV1) -> pl.DataFrame:
    """The standard signal frame for ``spec`` over ``candles``."""
    flags = spec_condition_frame(candles, spec)
    le, se, lx, sx = pl.col("le"), pl.col("se"), pl.col("lx"), pl.col("sx")
    conflict = le & se
    le_ok = le & ~conflict
    se_ok = se & ~conflict
    signal = (
        pl.when(lx & sx)
        .then(pl.lit("EXIT"))
        .when(lx)
        .then(pl.when(se_ok).then(pl.lit("SELL")).otherwise(pl.lit("EXIT_LONG")))
        .when(sx)
        .then(pl.when(le_ok).then(pl.lit("BUY")).otherwise(pl.lit("EXIT_SHORT")))
        .when(le_ok)
        .then(pl.lit("BUY"))
        .when(se_ok)
        .then(pl.lit("SELL"))
        .otherwise(pl.lit("HOLD"))
    )
    out = flags.select(
        pl.col("timestamp"),
        signal.alias("signal_type"),
        pl.lit(None, dtype=pl.Float64).alias("stop_price"),
        pl.lit(None, dtype=pl.Float64).alias("target_price"),
    )
    return out.cast(SIGNAL_SCHEMA)  # type: ignore[arg-type]


def spec_exit_config(spec: StrategySpecV1) -> ExitConfig:
    risk, session = spec.risk, spec.session
    kw: dict[str, Any] = {
        "session_start": session.entry_start,
        "session_end": session.entry_end,
        "eod_squareoff": session.squareoff_time if session.eod_squareoff else None,
        "time_stop_bars": risk.time_stop_bars or 0,
    }
    stop = risk.stop
    if stop.mode == "pct":
        kw.update(stop_mode="pct", stop_pct=stop.value / 100.0)
    elif stop.mode == "points":
        kw.update(stop_mode="points", stop_points=stop.value)
    elif stop.mode == "atr":
        kw.update(stop_mode="atr", stop_atr_mult=stop.value)
    target = risk.target
    if target.mode == "pct":
        kw.update(target_mode="pct", target_pct=target.value / 100.0)
    elif target.mode == "points":
        kw.update(target_mode="points", target_points=target.value)
    elif target.mode == "atr":
        kw.update(target_mode="atr", target_atr_mult=target.value)
    elif target.mode == "r_multiple":
        kw.update(target_mode="r_multiple", target_r_multiple=target.value)
    trail = risk.trail
    if trail.mode in ("atr", "breakeven_then_atr"):
        kw.update(trail_mode=trail.mode, trail_atr_mult=trail.value)
    return ExitConfig(**kw)


def spec_backtest_config(
    spec: StrategySpecV1, *, lot_size: int = NIFTY_LOT_SIZE
) -> BacktestConfig:
    return BacktestConfig(
        position_size=spec.sizing.lots,
        lot_size=lot_size,
        costs=CostConfig(),
        execution=ExecutionConfig(slippage=SlippageConfig(mode=spec.execution.slippage)),
        exits=spec_exit_config(spec),
    )
