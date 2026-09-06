"""S4 -- Opening Range Breakout + VWAP/ATR filter.

The widely-replicated Indian-intraday ORB family. Enters on the first
close beyond the opening range (first ``or_minutes`` of the session),
gated by range-vs-ATR (skip a breakout of a range too small to be
meaningful) and optionally VWAP-side confirmation.

VWAP needs real traded volume to mean anything. On index spot (volume
all-zero), ``quant.indicators.structure.add_vwap`` falls back to an
unweighted running mean of the typical price and flags
``vwap_is_proxy=True`` -- carried through to the signal output as a
diagnostic so downstream leaderboard/gate logic can treat spot runs of
this strategy as screening only, never promotion, without this module
needing to know its own data source.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import polars as pl

from quant.candles.session import parse_time
from quant.indicators.atr import add_atr
from quant.indicators.structure import add_session_levels, add_vwap
from quant.strategies._common import finalize_signals
from quant.strategies.base import StrategySpec, register_strategy

STRATEGY_ID = "orb_vwap"

PARAM_SPACE: dict[str, tuple[Any, ...]] = {
    "or_minutes": (15, 30, 45, 60),
    "min_or_atr": (0.5, 1.0, 1.5),
    "require_vwap": (True, False),
    "atr_period": (14,),
}


def _or_end_str(or_minutes: int) -> str:
    start = parse_time("09:15")
    from datetime import datetime as _dt

    end_dt = _dt(2000, 1, 1, start.hour, start.minute) + timedelta(minutes=or_minutes)
    return f"{end_dt.hour:02d}:{end_dt.minute:02d}"


def generate_signals(frame: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    or_minutes = int(params.get("or_minutes", 30))
    min_or_atr = float(params.get("min_or_atr", 1.0))
    require_vwap = bool(params.get("require_vwap", True))
    atr_period = int(params.get("atr_period", 14))

    or_end = _or_end_str(or_minutes)

    work = frame.sort("timestamp")
    work = add_atr(work, atr_period, name="atr")
    work = add_session_levels(work, start="09:15", end=or_end, prefix="or")
    work = add_vwap(work)

    n = work.height
    times = work["timestamp"].to_list()
    closes = work["close"].to_list()
    or_high = work["or_high"].to_list()
    or_low = work["or_low"].to_list()
    vwap = work["vwap"].to_list()
    atrs = work["atr"].to_list()
    vwap_is_proxy = bool(work["vwap_is_proxy"][0]) if n else False

    signal_type = ["HOLD"] * n
    stop_price: list[float | None] = [None] * n
    target_price: list[float | None] = [None] * n
    broken_today: set = set()

    for t in range(n):
        day = times[t].date()
        if day in broken_today:
            continue
        oh, ol, atr_t = or_high[t], or_low[t], atrs[t]
        if oh is None or ol is None or atr_t is None:
            continue
        or_range = oh - ol
        if or_range < min_or_atr * atr_t:
            continue

        if closes[t] > oh and (not require_vwap or closes[t] > vwap[t]):
            signal_type[t] = "BUY"
            stop_price[t] = (oh + ol) / 2.0
            broken_today.add(day)
        elif closes[t] < ol and (not require_vwap or closes[t] < vwap[t]):
            signal_type[t] = "SELL"
            stop_price[t] = (oh + ol) / 2.0
            broken_today.add(day)

    out = finalize_signals(work, signal_type, stop_price, target_price)
    return out.with_columns(pl.lit(vwap_is_proxy).alias("vwap_is_proxy"))


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        requires_volume=False,  # can run on spot (flagged vwap_is_proxy); real VWAP needs futures
        default_timeframes=("5m", "15m"),
        param_space=PARAM_SPACE,
        generate_signals=generate_signals,
        description="Opening range breakout with ATR/VWAP confirmation filter.",
    )
)
