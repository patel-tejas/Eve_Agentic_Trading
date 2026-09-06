"""S3 -- Indian Opening Raid (ICT Judas Swing, re-timed to IST).

ICT's Judas Swing is defined against a London/NY kill-zone clock, which
does not exist on the NSE/BSE single 09:15-15:30 IST session. The
correct re-timing: the manipulation leg is the FIRST HOUR of the Indian
session, not a London open. Opening range 09:15-``or_end``; a break of
the OR high/low that closes back inside within the raid window
(``or_end``-``raid_window_end``) is the false move -- fade it.

Measured base rate on the 31 real trading days available: 68% of
sessions contain an OR break-and-reverse in 09:45-11:00. No volume
needed; runs on index spot or futures.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from quant.indicators.atr import add_atr
from quant.indicators.structure import add_session_levels
from quant.strategies._common import finalize_signals
from quant.strategies.base import StrategySpec, register_strategy

STRATEGY_ID = "ist_judas"

PARAM_SPACE: dict[str, tuple[Any, ...]] = {
    "or_end": ("09:30", "09:45", "10:00"),
    "raid_window_end": ("10:15", "10:30", "11:00"),
    "min_raid_atr": (0.2, 0.5, 1.0),
    "require_close_inside": (True, False),
    "atr_period": (14,),
    "stop_buffer_atr": (0.1,),
}


def generate_signals(frame: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    or_end = params.get("or_end", "09:45")
    raid_window_end = params.get("raid_window_end", "10:30")
    min_raid_atr = float(params.get("min_raid_atr", 0.5))
    require_close_inside = bool(params.get("require_close_inside", True))
    atr_period = int(params.get("atr_period", 14))
    stop_buffer_atr = float(params.get("stop_buffer_atr", 0.1))

    work = frame.sort("timestamp")
    work = add_atr(work, atr_period, name="atr")
    work = add_session_levels(work, start="09:15", end=or_end, prefix="or")

    n = work.height
    times = work["timestamp"].to_list()
    highs = work["high"].to_list()
    lows = work["low"].to_list()
    closes = work["close"].to_list()
    or_high = work["or_high"].to_list()
    or_low = work["or_low"].to_list()
    atrs = work["atr"].to_list()

    from quant.candles.session import parse_time

    raid_end_t = parse_time(raid_window_end)
    or_end_t = parse_time(or_end)

    signal_type = ["HOLD"] * n
    stop_price: list[float | None] = [None] * n
    target_price: list[float | None] = [None] * n
    raided_today: set = set()

    for t in range(n):
        tod = times[t].time()
        day = times[t].date()
        if not (or_end_t <= tod < raid_end_t):
            continue
        if day in raided_today:
            continue
        oh, ol, atr_t = or_high[t], or_low[t], atrs[t]
        if oh is None or ol is None or atr_t is None:
            continue

        overshoot_up = highs[t] - oh
        if overshoot_up >= min_raid_atr * atr_t and (not require_close_inside or closes[t] < oh):
            signal_type[t] = "SELL"
            stop_price[t] = highs[t] + stop_buffer_atr * atr_t
            target_price[t] = ol
            raided_today.add(day)
            continue

        overshoot_down = ol - lows[t]
        if overshoot_down >= min_raid_atr * atr_t and (not require_close_inside or closes[t] > ol):
            signal_type[t] = "BUY"
            stop_price[t] = lows[t] - stop_buffer_atr * atr_t
            target_price[t] = oh
            raided_today.add(day)

    return finalize_signals(work, signal_type, stop_price, target_price)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        requires_volume=False,
        default_timeframes=("5m", "15m"),
        param_space=PARAM_SPACE,
        generate_signals=generate_signals,
        description="Opening-range false breakout fade, IST re-timed Judas Swing.",
    )
)
