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
