"""Relative Strength Index, Wilder's smoothing (Phase 15).

RSI = 100 - 100 / (1 + avg_gain / avg_loss), where the averages are Wilder
RMAs (EWM with alpha = 1/period), the same smoothing ``atr.py`` uses. The
first ``period`` rows are null (warm-up). When there were no losses in the
window RSI is 100; when there was no movement at all it is 50.

Causal: bar ``i`` uses ``close[i]`` and ``close[i-1]`` only, and the RMA only
looks backward.
"""

from __future__ import annotations

import polars as pl


def rsi_expr(period: int = 14, source: str = "close") -> pl.Expr:
    alpha = 1.0 / period
    delta = pl.col(source).diff()
    gain = pl.when(delta > 0).then(delta).otherwise(0.0)
    loss = pl.when(delta < 0).then(-delta).otherwise(0.0)
    avg_gain = gain.ewm_mean(alpha=alpha, adjust=False)
    avg_loss = loss.ewm_mean(alpha=alpha, adjust=False)
    rsi = (
        pl.when((avg_loss == 0) & (avg_gain == 0))
        .then(50.0)
        .when(avg_loss == 0)
        .then(100.0)
        .otherwise(100.0 - 100.0 / (1.0 + avg_gain / avg_loss))
    )
    # Row 0 has no delta; the RMA needs ``period`` deltas to be meaningful.
    return pl.when(pl.int_range(0, pl.len()) < period).then(None).otherwise(rsi)


def add_rsi(frame: pl.DataFrame, period: int = 14, source: str = "close") -> pl.DataFrame:
    return frame.with_columns(rsi_expr(period, source).alias(f"rsi_{period}"))
