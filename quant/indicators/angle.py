"""Normalized EMA angle.

Phase 02: normalized slope -> atan -> degrees, with frozen
angle_threshold / angle_lookback / angle_scale parameters.

Definition (proposal section 23):
    normalized_slope = (EMA[t] - EMA[t-k]) / EMA[t-k]
    angle           = atan(normalized_slope * scale) * (180 / pi)
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

DEGREES_PER_RADIAN = 180.0 / 3.141592653589793


@dataclass(frozen=True)
class AngleParams:
    """Frozen normalization parameters for the EMA angle."""

    threshold: float = 30.0  # degrees (signal filter)
    lookback: int = 1  # candles used for the slope
    scale: float = 1000.0  # normalization factor


def ema_angle_expr(
    ema_column: str,
    *,
    lookback: int = 1,
    scale: float = 1000.0,
) -> pl.Expr:
    """Angle (degrees) of the EMA at each bar, null where unavailable."""
    prev = pl.col(ema_column).shift(lookback)
    normalized_slope = (pl.col(ema_column) - prev) / prev
    return (normalized_slope * scale).arctan() * DEGREES_PER_RADIAN


def add_ema_angle(
    frame: pl.DataFrame,
    ema_column: str,
    *,
    name: str | None = None,
    lookback: int = 1,
    scale: float = 1000.0,
) -> pl.DataFrame:
    """Return ``frame`` with the EMA angle column attached."""
    column = name or f"{ema_column}_angle_deg"
    return frame.with_columns(
        ema_angle_expr(ema_column, lookback=lookback, scale=scale).alias(column)
    )


def ema_slope_atr_expr(
    ema_column: str,
    atr_column: str = "atr",
    *,
    lookback: int = 1,
) -> pl.Expr:
    """ATR-normalized EMA slope: ``(EMA[t] - EMA[t-k]) / (k * ATR[t])``.

    Phase 09: the fixed-scale ``ema_angle_expr`` above (``angle_scale``
    frozen at 1000) makes a nominal threshold mean wildly different things
    on different timeframes and lookbacks -- measured on real July 2026
    NIFTY data, a 30-degree threshold passes 0.55% of 1m/lookback=1 bars
    but 72.06% of 15m/lookback=5 bars (a 131x difference in selectivity
    for the "same" filter). Dividing by ``k * ATR`` instead of a fixed
    constant makes the resulting quantity a slope in VOLATILITY units,
    which is close to invariant across timeframe, lookback, and regime --
    measured p50/p70/p85/p95 of ``|slope|`` on 1m/5m/15m July data differ
    by only a few percent of each other, unlike the degree measure's
    131x spread. Dividing by ``k`` specifically is what decouples the
    threshold from ``lookback``: without it, a longer lookback would
    still inflate the raw numerator even after ATR-normalizing.

    Units: ATR per bar. A value of ``0.20`` means the EMA moved 0.20x an
    average true range over the lookback window, per bar.
    """
    prev = pl.col(ema_column).shift(lookback)
    return (pl.col(ema_column) - prev) / (lookback * pl.col(atr_column))


def add_ema_slope_atr(
    frame: pl.DataFrame,
    ema_column: str,
    *,
    atr_column: str = "atr",
    name: str | None = None,
    lookback: int = 1,
) -> pl.DataFrame:
    """Return ``frame`` with the ATR-normalized EMA slope column attached."""
    column = name or f"{ema_column}_slope_atr"
    return frame.with_columns(
        ema_slope_atr_expr(ema_column, atr_column, lookback=lookback).alias(column)
    )
