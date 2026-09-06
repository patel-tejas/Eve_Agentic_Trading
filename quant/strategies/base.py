"""Strategy registry (Phase 09).

Every strategy -- the incumbent EMA/angle family and the 5 new SMC/ICT
families -- is a plain function ``generate_signals(frame, params) ->
pl.DataFrame`` (matching ``quant.strategies.ema_9_15.generate_signals``'s
existing shape) plus a small ``StrategySpec`` describing it, so the sweep
harness (Phase 6) can treat every family identically without a class
hierarchy.

Output contract for every ``generate_signals``: one row per input bar,
columns ``timestamp, signal_type`` (``"BUY"|"SELL"|"HOLD"``), plus
``stop_price``/``target_price`` (nullable -- present so the engine can
run with ``ExitConfig(stop_mode="signal", target_mode="signal")``, since
SMC strategies need STRUCTURAL stops/targets, not a fixed N x ATR).

``requires_volume=True`` strategies (currently only ``orb_vwap`` in its
real-VWAP mode) must never be scheduled against a ``volume == 0``
dataset (index spot) for anything but screening -- the sweep planner
checks this before dispatch, not the strategy function itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import polars as pl

GenerateSignalsFn = Callable[[pl.DataFrame, Mapping[str, Any]], pl.DataFrame]


@dataclass(frozen=True)
class StrategySpec:
    """Everything the sweep harness needs to know about one strategy family."""

    id: str
    requires_volume: bool
    default_timeframes: tuple[str, ...]
    param_space: dict[str, tuple[Any, ...]]
    generate_signals: GenerateSignalsFn
    description: str = ""


STRATEGY_REGISTRY: dict[str, StrategySpec] = {}


def register_strategy(spec: StrategySpec) -> StrategySpec:
    """Register a strategy spec; returns it unchanged (usable as a decorator
    target or a plain call at module import time)."""
    if spec.id in STRATEGY_REGISTRY:
        raise ValueError(f"strategy id {spec.id!r} already registered")
    STRATEGY_REGISTRY[spec.id] = spec
    return spec


def get_strategy(strategy_id: str) -> StrategySpec:
    if strategy_id not in STRATEGY_REGISTRY:
        raise KeyError(
            f"unknown strategy {strategy_id!r}; known: {sorted(STRATEGY_REGISTRY)}"
        )
    return STRATEGY_REGISTRY[strategy_id]


def can_run_on(spec: StrategySpec, frame: pl.DataFrame) -> tuple[bool, str]:
    """Whether ``frame`` is a legal dataset for this strategy.

    Returns ``(True, "")`` if fine, else ``(False, reason)``. The
    mechanical guard against silently backtesting a volume-dependent
    strategy on index spot (``volume`` all zero).
    """
    if spec.requires_volume:
        if "volume" not in frame.columns or frame["volume"].sum() == 0:
            return False, (
                f"strategy {spec.id!r} requires real volume but the frame's "
                "volume is zero (index-spot proxy) -- refusing to schedule "
                "outside screening/diagnostic use"
            )
    return True, ""
