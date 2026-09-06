"""S2 -- Order Block + BOS/CHoCH Continuation (SMC).

A confirmed break of structure (BOS or CHoCH) publishes an order block
(the last opposite-colour candle before the displacement leg that
produced the break -- see ``quant.indicators.structure.add_order_blocks``,
which only surfaces an OB on the bar its break is itself confirmed).
Entry is the first retrace back into that block; stop beyond the block,
target the next confirmed swing level in the break's direction.

No volume needed; runs on index spot or futures.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from quant.indicators.atr import add_atr
from quant.indicators.structure import add_order_blocks, add_swings
from quant.strategies._common import finalize_signals, forward_fill_swing_levels
from quant.strategies.base import StrategySpec, register_strategy

STRATEGY_ID = "smc_ob_choch"

PARAM_SPACE: dict[str, tuple[Any, ...]] = {
    "swing_left": (2, 3, 5),
    "swing_right": (2, 3, 5),
    "displacement_atr_mult": (0.5, 1.0, 1.5),
    "ob_entry": ("mean", "high_low"),
    "ob_valid_bars": (10, 30, 60),
}


def generate_signals(frame: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    swing_left = int(params.get("swing_left", 3))
    swing_right = int(params.get("swing_right", 3))
    displacement_atr_mult = float(params.get("displacement_atr_mult", 1.0))
    ob_entry = params.get("ob_entry", "mean")
    ob_valid_bars = int(params.get("ob_valid_bars", 30))

    work = frame.sort("timestamp")
    work = add_atr(work, 14, name="atr")
    swings = add_swings(work, left=swing_left, right=swing_right)
    swings = forward_fill_swing_levels(swings)
    ob = add_order_blocks(
        work,
        swings=swings,
        left=swing_left,
        right=swing_right,
        displacement_atr_mult=displacement_atr_mult,
    )

    n = work.height
    highs = work["high"].to_list()
    lows = work["low"].to_list()
    last_swing_high = swings["last_swing_high"].to_list()
    last_swing_low = swings["last_swing_low"].to_list()
    ob_bullish = ob["ob_bullish"].to_list()
    ob_bearish = ob["ob_bearish"].to_list()
    ob_top = ob["ob_top"].to_list()
    ob_bottom = ob["ob_bottom"].to_list()

    signal_type = ["HOLD"] * n
    stop_price: list[float | None] = [None] * n
    target_price: list[float | None] = [None] * n

    # Pending zone: (ob_idx, top, bottom, direction)
    bull_zone: tuple[int, float, float] | None = None
    bear_zone: tuple[int, float, float] | None = None

    def _entry_level(top: float, bottom: float, side: str) -> float:
        if ob_entry == "high_low":
            return top if side == "bull" else bottom
        return (top + bottom) / 2.0

    for t in range(n):
        if ob_bullish[t]:
            bull_zone = (t, ob_top[t], ob_bottom[t])
        if ob_bearish[t]:
            bear_zone = (t, ob_top[t], ob_bottom[t])

        if bull_zone is not None:
            zone_idx, top, bottom = bull_zone
            if t - zone_idx > ob_valid_bars:
                bull_zone = None
            elif t > zone_idx and lows[t] <= _entry_level(top, bottom, "bull"):
                signal_type[t] = "BUY"
                stop_price[t] = bottom
                target_price[t] = last_swing_high[t]
                bull_zone = None

        if bear_zone is not None:
            zone_idx, top, bottom = bear_zone
            if t - zone_idx > ob_valid_bars:
                bear_zone = None
            elif t > zone_idx and highs[t] >= _entry_level(top, bottom, "bear"):
                signal_type[t] = "SELL"
                stop_price[t] = top
                target_price[t] = last_swing_low[t]
                bear_zone = None

    return finalize_signals(work, signal_type, stop_price, target_price)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        requires_volume=False,
        default_timeframes=("5m", "15m"),
        param_space=PARAM_SPACE,
        generate_signals=generate_signals,
        description="Order block retest continuation after a confirmed BOS/CHoCH.",
    )
)
