"""S5 -- PDH/PDL Sweep-and-Reverse ("Turtle Soup").

Entry: price closes beyond the previous day's high/low, then reverts
back inside within ``revert_bars`` -- fade the failed breakout.
Measured base rate on the 31 real trading days available: 60% of
sessions contain a PDH/PDL sweep-and-fail. Session: NSE/BSE
09:15-15:30 IST.

No volume needed; runs on index spot or futures.
"""

from __future__ import annotations

from datetime import time
from typing import Any

import polars as pl

from quant.indicators.atr import add_atr
from quant.indicators.structure import add_prev_day_levels
from quant.strategies._common import finalize_signals
from quant.strategies.base import StrategySpec, register_strategy

STRATEGY_ID = "pdh_pdl_turtle_soup"

PARAM_SPACE: dict[str, tuple[Any, ...]] = {
    "revert_bars": (1, 2, 3, 5),
    "min_overshoot_atr": (0.0, 0.25, 0.5),
    "entry_window": ("full_day", "09:15-13:00"),
    "target": ("pdc", "opposite_level", "r_multiple"),
    "atr_period": (14,),
    "stop_buffer_atr": (0.1,),
}


def generate_signals(frame: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """One row per bar; BUY/SELL fires the bar the failed breakout reverts."""
    revert_bars = int(params.get("revert_bars", 2))
    min_overshoot_atr = float(params.get("min_overshoot_atr", 0.25))
    entry_window = params.get("entry_window", "full_day")
    target_mode = params.get("target", "pdc")
    atr_period = int(params.get("atr_period", 14))
    stop_buffer_atr = float(params.get("stop_buffer_atr", 0.1))

    work = frame.sort("timestamp")
    work = add_atr(work, atr_period, name="atr")
    work = add_prev_day_levels(work)

    n = work.height
    times = work["timestamp"].to_list()
    highs = work["high"].to_list()
    lows = work["low"].to_list()
    closes = work["close"].to_list()
    pdh = work["pdh"].to_list()
    pdl = work["pdl"].to_list()
    pdc = work["pdc"].to_list()
    atrs = work["atr"].to_list()

    window_start = time(9, 15)
    window_end = time(13, 0) if entry_window == "09:15-13:00" else time(15, 30)

    signal_type = ["HOLD"] * n
    stop_price: list[float | None] = [None] * n
    target_price: list[float | None] = [None] * n

    # Pending raid state, at most one per direction at a time.
    high_raid_start: int | None = None  # index where close first > pdh
    high_raid_extreme: float | None = None
    low_raid_start: int | None = None
    low_raid_extreme: float | None = None

    for t in range(n):
        tod = times[t].time()
        atr_t = atrs[t]

        # -- update / detect a high-side (PDH) raid --------------------
        if high_raid_start is not None:
            high_raid_extreme = max(high_raid_extreme, highs[t])
            bars_since = t - high_raid_start
            if bars_since > revert_bars:
                high_raid_start = None
                high_raid_extreme = None
            elif closes[t] < pdh[t] and atr_t is not None:
                overshoot = high_raid_extreme - pdh[t]
                if overshoot >= min_overshoot_atr * atr_t:
                    signal_type[t] = "SELL"
                    stop_price[t] = high_raid_extreme + stop_buffer_atr * atr_t
                    if target_mode == "pdc":
                        target_price[t] = pdc[t]
                    elif target_mode == "opposite_level":
                        target_price[t] = pdl[t]
                    high_raid_start = None
                    high_raid_extreme = None
        if (
            high_raid_start is None
            and window_start <= tod < window_end
            and pdh[t] is not None
            and closes[t] > pdh[t]
        ):
            high_raid_start = t
            high_raid_extreme = highs[t]

        # -- update / detect a low-side (PDL) raid ---------------------
        if low_raid_start is not None:
            low_raid_extreme = min(low_raid_extreme, lows[t])
            bars_since = t - low_raid_start
            if bars_since > revert_bars:
                low_raid_start = None
                low_raid_extreme = None
            elif closes[t] > pdl[t] and atr_t is not None:
                overshoot = pdl[t] - low_raid_extreme
                if overshoot >= min_overshoot_atr * atr_t:
                    signal_type[t] = "BUY"
                    stop_price[t] = low_raid_extreme - stop_buffer_atr * atr_t
                    if target_mode == "pdc":
                        target_price[t] = pdc[t]
                    elif target_mode == "opposite_level":
                        target_price[t] = pdh[t]
                    low_raid_start = None
                    low_raid_extreme = None
        if (
            low_raid_start is None
            and window_start <= tod < window_end
            and pdl[t] is not None
            and closes[t] < pdl[t]
        ):
            low_raid_start = t
            low_raid_extreme = lows[t]

    return finalize_signals(work, signal_type, stop_price, target_price)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        requires_volume=False,
        default_timeframes=("5m", "15m"),
        param_space=PARAM_SPACE,
        generate_signals=generate_signals,
        description="Previous-day high/low sweep-and-reverse (Turtle Soup).",
    )
)
