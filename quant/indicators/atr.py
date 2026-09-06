"""Average True Range (Wilder).

Phase 09: causal ATR used to (a) normalize the EMA slope so a threshold
means the same thing on every timeframe, and (b) size stop/target/trail
distances in the bracket-exit engine. Wilder's smoothing is an EWM with
``alpha = 1/period`` (RMA), which is the standard convention.

Causal by construction: bar ``i``'s true range uses only ``close[i-1]``,
``high[i]``, ``low[i]`` (all known at or before bar ``i``'s close), and the
rolling mean only ever looks backward.
"""

from __future__ import annotations

import polars as pl


def true_range_expr() -> pl.Expr:
    """True range at each bar: max(high-low, |high-prev_close|, |low-prev_close|)."""
    prev_close = pl.col("close").shift(1)
    return pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - prev_close).abs(),
        (pl.col("low") - prev_close).abs(),
    )


def atr_expr(period: int = 14, *, name: str | None = None) -> pl.Expr:
    """Wilder ATR(period): RMA of true range, alpha = 1/period, causal."""
    alpha = 1.0 / period
    return (
        true_range_expr()
        .ewm_mean(alpha=alpha, adjust=False, min_samples=period)
        .alias(name or f"atr_{period}")
    )


def add_atr(frame: pl.DataFrame, period: int = 14, *, name: str | None = None) -> pl.DataFrame:
    """Return ``frame`` with the ATR(period) column attached.

    Requires ``high``, ``low``, ``close`` columns. Null for the warm-up
    (first ``period`` rows), matching ``quant.indicators.ema.add_ema``.
    """
    return frame.with_columns(atr_expr(period, name=name))
