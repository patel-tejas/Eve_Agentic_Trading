"""Bollinger Bands (Phase 15): SMA(N) +/- k * population stdev(N). Causal, null warm-up."""

from __future__ import annotations

import polars as pl


def bollinger_exprs(
    period: int = 20, stddev: float = 2.0, source: str = "close"
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    mid = pl.col(source).rolling_mean(window_size=period, min_samples=period)
    sd = pl.col(source).rolling_std(window_size=period, min_samples=period, ddof=0)
    return mid + stddev * sd, mid, mid - stddev * sd


def add_bollinger(frame: pl.DataFrame, period: int = 20, stddev: float = 2.0) -> pl.DataFrame:
    upper, mid, lower = bollinger_exprs(period, stddev)
    tag = f"{period}_{stddev:g}"
    return frame.with_columns(
        upper.alias(f"bb_upper_{tag}"), mid.alias(f"bb_mid_{tag}"), lower.alias(f"bb_lower_{tag}")
    )
