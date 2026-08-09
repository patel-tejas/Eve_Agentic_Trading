"""Exponential Moving Average.

Phase 02: EMA(N) with alpha = 2 / (N + 1), warm-up rows (first N-1)
kept as null per the research spec.
"""

from __future__ import annotations

import polars as pl

DEFAULT_EMA_PERIODS = (9, 15)


def ema_expr(period: int, source: str = "close") -> pl.Expr:
    """EMA(N) over ``source``; null for the first N-1 rows (warm-up)."""
    alpha = 2.0 / (period + 1)
    return (
        pl.col(source)
        .ewm_mean(alpha=alpha, adjust=False, min_samples=period)
        .alias(f"ema_{source}_{period}" if source != "close" else f"ema_{period}")
    )


def add_ema(
    frame: pl.DataFrame,
    period: int,
    source: str = "close",
) -> pl.DataFrame:
    """Return ``frame`` with the EMA(period) column attached."""
    name = f"ema_{source}_{period}" if source != "close" else f"ema_{period}"
    return frame.with_columns(ema_expr(period, source).alias(name))
