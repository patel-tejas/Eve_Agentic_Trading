"""Candle aggregation.

Phase 03: build 5m/15m (and other) candles from canonical 1m data.

Aggregation rules (per phase spec):
    open  = first candle's open
    high  = max of highs
    low   = min of lows
    close = last candle's close
    volume  = sum of volumes
    oi    = last candle's OI
Metadata columns (instrument, security_id, expiry, ...) keep the first value.
"""

from __future__ import annotations

import polars as pl

AGGREGATE_COLUMNS = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
)


def aggregate_candles(frame: pl.DataFrame, minutes: int) -> pl.DataFrame:
    """Aggregate 1-minute candles into ``minutes``-minute candles.

    Boundaries align to the first data point, which for aligned daily
    sessions is also wall-clock aligned (5m/15m divide the trading day).
    """
    if minutes <= 1:
        return frame.sort("timestamp")

    meta_columns = [c for c in frame.columns if c not in AGGREGATE_COLUMNS]
    agg = {c: pl.col(c).first() for c in meta_columns}
    agg.update(
        {
            "open": pl.col("open").first(),
            "high": pl.col("high").max(),
            "low": pl.col("low").min(),
            "close": pl.col("close").last(),
            "volume": pl.col("volume").sum(),
            "open_interest": pl.col("open_interest").last(),
        }
    )
    return (
        frame.sort("timestamp")
        .group_by_dynamic(
            "timestamp",
            every=f"{minutes}m",
            closed="left",
            label="left",
        )
        .agg(**agg)
        .sort("timestamp")
    )
