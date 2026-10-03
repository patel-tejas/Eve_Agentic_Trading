"""Simple Moving Average (Phase 15).

SMA(N) = mean of the last N closes, null for the first N-1 rows (warm-up),
matching ``quant.indicators.ema``'s convention. Causal: a rolling window only
ever looks backward.
"""

from __future__ import annotations

import polars as pl


def sma_expr(period: int, source: str = "close") -> pl.Expr:
    return pl.col(source).rolling_mean(window_size=period, min_samples=period)


def add_sma(frame: pl.DataFrame, period: int, source: str = "close") -> pl.DataFrame:
    name = f"sma_{source}_{period}" if source != "close" else f"sma_{period}"
    return frame.with_columns(sma_expr(period, source).alias(name))
