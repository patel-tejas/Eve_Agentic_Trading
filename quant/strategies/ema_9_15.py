"""Baseline strategy: 9 EMA / 15 EMA crossover + angle filter.

Phase 04: BUY on bullish crossover AND fast-angle >= +threshold,
SELL on bearish crossover AND fast-angle <= -threshold, else HOLD.

Engine contract
- The strategy recomputes every indicator from OHLCV itself; it never
  trusts indicator columns in the input frame. Same input -> same output.
- No look-ahead: at bar ``t`` only candles ``<= t`` are used (EMA is
  causal; crossover uses ``t-1``; angle is defined at the close of ``t``).
- Seed window: the first ``slow_ema - 1`` bars carry no slow EMA and are
  always HOLD, even if prices would cross there.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

import polars as pl
from pydantic import BaseModel, field_validator, model_validator

from quant.indicators.angle import add_ema_angle
from quant.indicators.ema import add_ema

SignalType = Literal["BUY", "SELL", "HOLD"]


class StrategyConfig(BaseModel):
    """Frozen strategy parameters (research spec, phase 04)."""

    fast_ema: int = 9
    slow_ema: int = 15
    angle_threshold: float = 30.0  # degrees
    angle_lookback: int = 1
    angle_scale: float = 1000.0  # normalization factor
    signal_mode: Literal["crossover_and_angle"] = "crossover_and_angle"

    @model_validator(mode="after")
    def _validate_periods(self) -> "StrategyConfig":
        if self.fast_ema <= 0:
            raise ValueError("fast_ema must be > 0")
        if self.slow_ema <= self.fast_ema:
            raise ValueError("slow_ema must be greater than fast_ema")
        return self

    @field_validator("angle_threshold", "angle_scale")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("angle_lookback")
    @classmethod
    def _lookback_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("angle_lookback must be >= 1")
        return v


@dataclass(frozen=True)
class Signal:
    """One bar-level signal row (schema from phase 04 spec)."""

    timestamp: datetime
    timeframe: str
    signal_type: SignalType
    ema_fast: float | None
    ema_slow: float | None
    angle: float | None
    crossover: bool
    candle_close: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def generate_signals(
    frame: pl.DataFrame,
    *,
    config: StrategyConfig | dict[str, object] | None = None,
    timeframe: str = "1m",
) -> pl.DataFrame:
    """Run the strategy over a candle frame.

    Input needs at least ``timestamp`` and ``close``. Output is one row
    per input bar (HOLD rows included) with the fixed signal schema:

        timestamp, signal_type, crossover, ema_fast, ema_slow, angle, candle_close
    """
    cfg = (
        StrategyConfig()
        if config is None
        else (config if isinstance(config, StrategyConfig) else StrategyConfig(**config))
    )
    if not {"timestamp", "close"}.issubset(frame.columns):
        raise ValueError("frame needs at least 'timestamp' and 'close' columns")

    fast, slow, angle_col = column_names(cfg)
    work = frame.sort("timestamp").select(pl.col("timestamp"), pl.col("close"))
    work = add_ema(work, cfg.fast_ema)
    work = add_ema(work, cfg.slow_ema)
    work = add_ema_angle(
        work,
        fast,
        name=angle_col,
        lookback=cfg.angle_lookback,
        scale=cfg.angle_scale,
    )

    f, s = pl.col(fast), pl.col(slow)
    prev_f, prev_s = f.shift(1), s.shift(1)
    crossover_up = (f > s) & (prev_f <= prev_s)
    crossover_down = (f < s) & (prev_f >= prev_s)

    angle = pl.col(angle_col)
    signal_type = (
        pl.when(crossover_up & (angle >= cfg.angle_threshold))
        .then(pl.lit("BUY"))
        .when(crossover_down & (angle <= -cfg.angle_threshold))
        .then(pl.lit("SELL"))
        .otherwise(pl.lit("HOLD"))
    )

    return (
        work.with_columns(
            signal_type.alias("signal_type"),
            (crossover_up | crossover_down).fill_null(False).alias("crossover"),
        )
        .rename({"close": "candle_close"})
        .select(
            "timestamp",
            "signal_type",
            "crossover",
            pl.col(fast).alias("ema_fast"),
            pl.col(slow).alias("ema_slow"),
            pl.col(angle_col).alias("angle"),
            "candle_close",
        )
    )


def column_names(cfg: StrategyConfig) -> tuple[str, str, str]:
    """EMA column names used by the engine for a given configuration."""
    return (
        f"ema_{cfg.fast_ema}",
        f"ema_{cfg.slow_ema}",
        f"ema_{cfg.fast_ema}_angle_deg",
    )


def signal_events(
    signals: pl.DataFrame,
    *,
    timeframe: str = "1m",
) -> list[Signal]:
    """Extract non-HOLD bars as Signal objects (chronological)."""
    events = signals.filter(pl.col("signal_type") != "HOLD").sort("timestamp")
    return [
        Signal(
            timestamp=row["timestamp"],
            timeframe=timeframe,
            signal_type=row["signal_type"],
            ema_fast=row["ema_fast"],
            ema_slow=row["ema_slow"],
            angle=row["angle"],
            crossover=bool(row["crossover"]),
            candle_close=row["candle_close"],
        )
        for row in events.to_dicts()
    ]
