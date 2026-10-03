"""MACD (Phase 15): line = EMA(fast) - EMA(slow), signal = EMA(line, n), hist = line - signal.

Uses the same EMA convention as ``ema.py`` (alpha = 2/(N+1), adjust=False,
null warm-up). The signal EMA starts only once the line exists, so the
first ``slow + signal - 2`` rows of ``signal``/``hist`` are null. Causal.
"""

from __future__ import annotations

import polars as pl


def _ema(expr: pl.Expr, period: int) -> pl.Expr:
    return expr.ewm_mean(alpha=2.0 / (period + 1), adjust=False, min_samples=period)


def macd_exprs(
    fast: int = 12, slow: int = 26, signal: int = 9, source: str = "close"
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    line = _ema(pl.col(source), fast) - _ema(pl.col(source), slow)
    sig = _ema(line, signal)
    return line, sig, line - sig


def add_macd(
    frame: pl.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> pl.DataFrame:
    line, sig, hist = macd_exprs(fast, slow, signal)
    tag = f"{fast}_{slow}_{signal}"
    return frame.with_columns(
        line.alias(f"macd_line_{tag}"),
        sig.alias(f"macd_signal_{tag}"),
        hist.alias(f"macd_hist_{tag}"),
    )
