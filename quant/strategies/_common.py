"""Shared helpers for the SMC/ICT strategy modules.

All five strategies build on the causal primitives in
``quant.indicators.structure`` and ``quant.indicators.atr``. This module
just avoids repeating the same "attach ATR + whichever structural
columns this strategy needs" boilerplate five times.
"""

from __future__ import annotations

from datetime import time

import polars as pl

SIGNAL_SCHEMA = {
    "timestamp": pl.Datetime("ms"),
    "signal_type": pl.Utf8,
    "stop_price": pl.Float64,
    "target_price": pl.Float64,
}

EMPTY_SIGNAL_COLUMNS = ("timestamp", "signal_type", "stop_price", "target_price")


def add_time_of_day(frame: pl.DataFrame, *, timestamp_col: str = "timestamp") -> pl.DataFrame:
    return frame.with_columns(pl.col(timestamp_col).dt.time().alias("_tod"))


def forward_fill_swing_levels(frame: pl.DataFrame) -> pl.DataFrame:
    """Forward-fill the confirmed swing levels so every bar carries the
    MOST RECENTLY confirmed high/low, not just the confirmation bar
    itself. Still causal: forward_fill only ever propagates a value into
    LATER rows."""
    return frame.with_columns(
        pl.col("swing_high_level").forward_fill().alias("last_swing_high"),
        pl.col("swing_low_level").forward_fill().alias("last_swing_low"),
    )


def finalize_signals(
    frame: pl.DataFrame,
    signal_type: list[str],
    stop_price: list[float | None],
    target_price: list[float | None],
) -> pl.DataFrame:
    """Assemble the standard 4-column signal output every strategy returns."""
    return pl.DataFrame(
        {
            "timestamp": frame["timestamp"].to_list(),
            "signal_type": signal_type,
            "stop_price": stop_price,
            "target_price": target_price,
        },
        schema=SIGNAL_SCHEMA,
    )


def time_in_window(t: time, start: time, end: time) -> bool:
    return start <= t < end
