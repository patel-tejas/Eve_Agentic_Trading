"""S1 -- Liquidity Sweep + FVG Reversal (ICT).

Price sweeps a reference level (previous-day high/low by default),
closes back inside within a few bars (liquidity taken, rejected), the
displacement leg away from the sweep prints a fair value gap, and entry
is on the retrace back into that gap. Structural stop beyond the sweep
extreme; structural target is the opposing reference level.

Mechanically close to Turtle Soup (S5) and shares its base-rate
evidence: PDH/PDL sweep-and-fail measured at 60% of the 31 available
sessions.

No volume needed; runs on index spot or futures.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from quant.indicators.atr import add_atr
from quant.indicators.structure import add_fvg, add_prev_day_levels, add_session_levels, add_swings
from quant.strategies._common import finalize_signals, forward_fill_swing_levels
from quant.strategies.base import StrategySpec, register_strategy

STRATEGY_ID = "smc_sweep_fvg"

PARAM_SPACE: dict[str, tuple[Any, ...]] = {
    "sweep_level": ("pdh_pdl", "session_hl", "prev_swing"),
    "displacement_atr_mult": (0.8, 1.2, 1.8),
    "fvg_valid_bars": (5, 10, 20),
    "max_sweep_to_fvg": (1, 2, 3),
    "atr_period": (14,),
    "stop_buffer_atr": (0.2,),
}


def generate_signals(frame: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    sweep_level = params.get("sweep_level", "pdh_pdl")
    displacement_atr_mult = float(params.get("displacement_atr_mult", 1.2))
    fvg_valid_bars = int(params.get("fvg_valid_bars", 10))
    max_sweep_to_fvg = int(params.get("max_sweep_to_fvg", 2))
    atr_period = int(params.get("atr_period", 14))
    stop_buffer_atr = float(params.get("stop_buffer_atr", 0.2))

    work = frame.sort("timestamp")
    work = add_atr(work, atr_period, name="atr")
    work = add_fvg(work)

    if sweep_level == "pdh_pdl":
        work = add_prev_day_levels(work)
        high_ref_col, low_ref_col = "pdh", "pdl"
    elif sweep_level == "session_hl":
        work = add_session_levels(work, start="09:15", end="09:45", prefix="or")
        high_ref_col, low_ref_col = "or_high", "or_low"
    elif sweep_level == "prev_swing":
        work = add_swings(work)
        work = forward_fill_swing_levels(work)
        high_ref_col, low_ref_col = "last_swing_high", "last_swing_low"
    else:
        raise ValueError(f"unknown sweep_level {sweep_level!r}")

    n = work.height
    highs = work["high"].to_list()
    lows = work["low"].to_list()
    closes = work["close"].to_list()
    opens = work["open"].to_list()
    high_ref = work[high_ref_col].to_list()
    low_ref = work[low_ref_col].to_list()
    fvg_bullish = work["fvg_bullish"].to_list()
    fvg_bearish = work["fvg_bearish"].to_list()
    fvg_top = work["fvg_top"].to_list()
    fvg_bottom = work["fvg_bottom"].to_list()
    atrs = work["atr"].to_list()

    signal_type = ["HOLD"] * n
    stop_price: list[float | None] = [None] * n
    target_price: list[float | None] = [None] * n

    # Pending state per direction: (sweep_idx, sweep_extreme) while
    # waiting for a displacement FVG; then (fvg_idx, top, bottom,
    # sweep_extreme) while waiting for the retrace entry.
    bull_sweep: tuple[int, float] | None = None
    bull_zone: tuple[int, float, float, float] | None = None
    bear_sweep: tuple[int, float] | None = None
    bear_zone: tuple[int, float, float, float] | None = None

    for t in range(n):
        hr, lr, atr_t = high_ref[t], low_ref[t], atrs[t]

        # --- bullish side: sweep of the LOW reference, then bullish FVG ---
        if bull_zone is not None:
            fvg_idx, top, bottom, sweep_low = bull_zone
            if t - fvg_idx > fvg_valid_bars:
                bull_zone = None
            elif lows[t] <= top:
                signal_type[t] = "BUY"
                stop_price[t] = sweep_low - stop_buffer_atr * (atr_t or 0.0)
                target_price[t] = hr
                bull_zone = None
        if bull_zone is None and bull_sweep is not None:
            sweep_idx, sweep_low = bull_sweep
            if t - sweep_idx > max_sweep_to_fvg:
                bull_sweep = None
            elif fvg_bullish[t] and atr_t is not None:
                displacement_body = abs(closes[t - 1] - opens[t - 1]) if t >= 1 else 0.0
                if displacement_body >= displacement_atr_mult * atr_t:
                    bull_zone = (t, fvg_top[t], fvg_bottom[t], sweep_low)
                    bull_sweep = None
        if bull_sweep is None and lr is not None and lows[t] < lr and closes[t] > lr:
            bull_sweep = (t, lows[t])

        # --- bearish side: sweep of the HIGH reference, then bearish FVG ---
        if bear_zone is not None:
            fvg_idx, top, bottom, sweep_high = bear_zone
            if t - fvg_idx > fvg_valid_bars:
                bear_zone = None
            elif highs[t] >= bottom:
                signal_type[t] = "SELL"
                stop_price[t] = sweep_high + stop_buffer_atr * (atr_t or 0.0)
                target_price[t] = lr
                bear_zone = None
        if bear_zone is None and bear_sweep is not None:
            sweep_idx, sweep_high = bear_sweep
            if t - sweep_idx > max_sweep_to_fvg:
                bear_sweep = None
            elif fvg_bearish[t] and atr_t is not None:
                displacement_body = abs(closes[t - 1] - opens[t - 1]) if t >= 1 else 0.0
                if displacement_body >= displacement_atr_mult * atr_t:
                    bear_zone = (t, fvg_top[t], fvg_bottom[t], sweep_high)
                    bear_sweep = None
        if bear_sweep is None and hr is not None and highs[t] > hr and closes[t] < hr:
            bear_sweep = (t, highs[t])

    return finalize_signals(work, signal_type, stop_price, target_price)


register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        requires_volume=False,
        default_timeframes=("5m", "15m"),
        param_space=PARAM_SPACE,
        generate_signals=generate_signals,
        description="Liquidity sweep + fair value gap reversal.",
    )
)
