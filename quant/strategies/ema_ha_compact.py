"""HA-compact-candle EMA crossover strategy.

A Heikin-Ashi-based EMA crossover strategy with three tunable gates:

1. **Compact Candle**: current HA range <= SMA(ha_range, lookback) * multiplier.
   A compact HA candle signals indecision / loss of momentum right at the cross.

2. **Slope Filter**: |EMA_slope| >= slope_threshold (ATR-normalized or fixed-scale).
   Ensures the crossover is backed by directional momentum.

3. **Distance Filter**: EMA gap as % of price >= min_distance_pct.
   Prevents entries where EMAs are too tightly coiled (noise).

4. **Volume Filter** (optional): volume > SMA(volume, period) * multiplier.
   Only meaningful on instruments with real volume (futures). Off by default
   since index spot has volume=0.

Entry logic:
- BUY: fast EMA crosses above slow EMA AND compact candle AND slope gate
        AND distance gate AND (volume gate if enabled).
- SELL: mirror for bearish cross.
- Stops use ATR brackets (ExitConfig), fills at next bar open + slippage.

No look-ahead: every indicator is causal (EMA, SMA, ATR are rolling-backward
constructs; HA is causal by construction). Seed window for slow EMA is always
HOLD.

Engine contract (matches STRATEGY_REGISTRY):
    generate_signals(frame, params) -> pl.DataFrame
    with columns: timestamp, signal_type, stop_price, target_price
"""

from __future__ import annotations

from typing import Any

import polars as pl
from pydantic import BaseModel, field_validator, model_validator

from quant.indicators.atr import add_atr
from quant.indicators.ema import add_ema
from quant.indicators.heikin_ashi import add_heikin_ashi
from quant.strategies._common import finalize_signals
from quant.strategies.base import StrategySpec, register_strategy

STRATEGY_ID = "ema_ha_compact"


class StrategyConfig(BaseModel):
    """All tunable parameters for the HA compact candle strategy."""

    # EMA periods
    fast_ema: int = 9
    slow_ema: int = 15

    # Compact candle gate
    compact_lookback: int = 20  # SMA window for HA range
    compact_multiplier: float = 1.0  # multiplier on SMA; <=1.0 = strict

    # Slope gate (ATR-normalized, matches ema_9_15 convention)
    slope_threshold_atr: float = 0.0  # 0.0 = gate off
    slope_lookback: int = 1
    atr_period: int = 14

    # Distance gate: fast-slow gap as % of price
    min_distance_pct: float = 0.0  # 0.0 = gate off
    max_distance_pct: float = 999.0  # very large = effectively off

    # Volume gate (optional)
    volume_filter_on: bool = False
    volume_sma_period: int = 20
    volume_multiplier: float = 1.0  # volume > SMA * multiplier

    @model_validator(mode="after")
    def _validate(self) -> "StrategyConfig":
        if self.fast_ema <= 0:
            raise ValueError("fast_ema must be > 0")
        if self.slow_ema <= self.fast_ema:
            raise ValueError("slow_ema must be greater than fast_ema")
        if self.compact_lookback < 1:
            raise ValueError("compact_lookback must be >= 1")
        return self

    @field_validator(
        "compact_multiplier", "slope_threshold_atr", "min_distance_pct",
        "max_distance_pct", "volume_multiplier",
    )
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("compact_lookback", "slope_lookback", "atr_period", "volume_sma_period")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v


def _prepare(frame: pl.DataFrame, cfg: StrategyConfig) -> pl.DataFrame:
    """Attach EMA, ATR, HA, compact-candle, slope, and distance columns."""
    work = frame.sort("timestamp")
    work = add_ema(work, cfg.fast_ema)
    work = add_ema(work, cfg.slow_ema)
    work = add_atr(work, cfg.atr_period, name="_atr")
    work = add_heikin_ashi(work)

    # HA range and its SMA for compact candle gate
    work = work.with_columns(
        (pl.col("ha_high") - pl.col("ha_low")).alias("_ha_range")
    )
    work = work.with_columns(
        pl.col("_ha_range").rolling_mean(window_size=cfg.compact_lookback).alias("_sma_ha_range")
    )
    work = work.with_columns(
        (pl.col("_ha_range") <= pl.col("_sma_ha_range") * cfg.compact_multiplier).alias(
            "_is_compact"
        )
    )

    # EMA slope (ATR-normalized): (fast[t] - fast[t-1]) / ATR
    work = work.with_columns(
        (pl.col(f"ema_{cfg.fast_ema}") - pl.col(f"ema_{cfg.fast_ema}").shift(1)).alias(
            "_ema_fast_delta"
        )
    )
    work = work.with_columns(
        (pl.col("_ema_fast_delta") / pl.col("_atr")).alias("_slope_atr")
    )

    # Distance: fast-slow gap as % of close
    work = work.with_columns(
        (
            (pl.col(f"ema_{cfg.fast_ema}") - pl.col(f"ema_{cfg.slow_ema}")).abs()
            / pl.col("close")
            * 100.0
        ).alias("_distance_pct")
    )

    # Volume SMA (if needed)
    if cfg.volume_filter_on and "volume" in frame.columns:
        work = work.with_columns(
            pl.col("volume").rolling_mean(window_size=cfg.volume_sma_period).alias("_vol_sma")
        )

    return work


def generate_signals(
    frame: pl.DataFrame, params: dict[str, Any]
) -> pl.DataFrame:
    """Registry entry point: one row per bar, BUY/SELL/HOLD with structural
    stop_price/target_price columns for ExitConfig integration."""
    cfg = StrategyConfig(**params)
    work = _prepare(frame, cfg)

    fast = pl.col(f"ema_{cfg.fast_ema}")
    slow = pl.col(f"ema_{cfg.slow_ema}")
    prev_fast = fast.shift(1)
    prev_slow = slow.shift(1)

    crossover_up = (fast > slow) & (prev_fast <= prev_slow)
    crossover_down = (fast < slow) & (prev_fast >= prev_slow)

    # Compact candle gate
    compact_buy = pl.col("_is_compact")
    compact_sell = pl.col("_is_compact")

    # Slope gate
    if cfg.slope_threshold_atr > 0.0:
        slope_buy = pl.col("_slope_atr") >= cfg.slope_threshold_atr
        slope_sell = pl.col("_slope_atr") <= -cfg.slope_threshold_atr
    else:
        slope_buy = pl.lit(True)
        slope_sell = pl.lit(True)

    # Distance gate
    if cfg.min_distance_pct > 0.0 or cfg.max_distance_pct < 999.0:
        dist_buy = (
            (pl.col("_distance_pct") >= cfg.min_distance_pct)
            & (pl.col("_distance_pct") <= cfg.max_distance_pct)
        )
        dist_sell = dist_buy  # same distance constraint for both directions
    else:
        dist_buy = pl.lit(True)
        dist_sell = pl.lit(True)

    # Volume gate (optional)
    if cfg.volume_filter_on and "_vol_sma" in work.columns:
        vol_gate = pl.col("volume") > pl.col("_vol_sma") * cfg.volume_multiplier
    else:
        vol_gate = pl.lit(True)

    signal_buy = crossover_up & compact_buy & slope_buy & dist_buy & vol_gate
    signal_sell = crossover_down & compact_sell & slope_sell & dist_sell & vol_gate

    signal_type = (
        pl.when(signal_buy)
        .then(pl.lit("BUY"))
        .when(signal_sell)
        .then(pl.lit("SELL"))
        .otherwise(pl.lit("HOLD"))
    )

    # Structural stop: ATR-based, set via ExitConfig(stop_mode="atr") on
    # the backtest side. We emit null stop_price/target_price here so the
    # engine uses its own bracket logic.
    out = work.with_columns(
        signal_type.alias("signal_type"),
        pl.lit(None, dtype=pl.Float64).alias("stop_price"),
        pl.lit(None, dtype=pl.Float64).alias("target_price"),
    )

    return finalize_signals(
        out,
        out["signal_type"].to_list(),
        out["stop_price"].to_list(),
        out["target_price"].to_list(),
    )


PARAM_SPACE: dict[str, tuple[Any, ...]] = {
    "fast_ema": (5, 7, 9, 12),
    "slow_ema": (15, 21, 25, 34),
    "compact_lookback": (10, 15, 20, 30),
    "compact_multiplier": (0.6, 0.8, 1.0, 1.2),
    "slope_threshold_atr": (0.0, 0.10, 0.20, 0.30),
    "slope_lookback": (1, 3, 5),
    "min_distance_pct": (0.0, 0.02, 0.05),
    "max_distance_pct": (0.5, 1.0, 2.0, 999.0),
    "volume_filter_on": (False, True),
    "volume_sma_period": (10, 20),
    "volume_multiplier": (0.8, 1.0, 1.5),
    "atr_period": (10, 14, 20),
}

register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        requires_volume=False,
        default_timeframes=("1m", "5m", "15m"),
        param_space=PARAM_SPACE,
        generate_signals=generate_signals,
        description=(
            "Heikin-Ashi EMA crossover with compact-candle, slope, distance, "
            "and optional volume gates. Designed for NIFTY/BANKNIFTY/SENSEX "
            "multi-timeframe optimization."
        ),
    )
)
