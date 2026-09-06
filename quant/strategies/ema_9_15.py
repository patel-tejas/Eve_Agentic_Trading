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

from quant.indicators.angle import DEGREES_PER_RADIAN, add_ema_angle, add_ema_slope_atr
from quant.indicators.atr import add_atr
from quant.indicators.ema import add_ema

SignalType = Literal["BUY", "SELL", "HOLD"]


class StrategyConfig(BaseModel):
    """Frozen strategy parameters (research spec, phase 04)."""

    fast_ema: int = 9
    slow_ema: int = 15
    angle_threshold: float = 30.0  # degrees
    angle_lookback: int = 1
    angle_scale: float = 1000.0  # normalization factor
    signal_mode: Literal["crossover", "crossover_and_angle", "crossover_angle_and_trend"] = (
        "crossover_and_angle"
    )

    # Phase 09: ATR-normalized slope gate, additive and off by default.
    # ``angle_mode="fixed_scale"`` (the default) reproduces the exact
    # pre-Phase-09 behaviour byte-for-bit -- see
    # ``tests/test_phase09_angle.py::test_fixed_scale_is_byte_identical_to_legacy``.
    # ``slope_threshold_atr`` ships NEUTRAL (0.0 = gate off): the invariant
    # percentile table this feature was measured against (July 2026 NIFTY)
    # sits inside the train split, so it is evidence for ATR-normalization
    # being timeframe-invariant, not a defensible shipped default -- the
    # sweep picks this value, not this file.
    angle_mode: Literal["fixed_scale", "atr_normalized"] = "fixed_scale"
    atr_period: int = 14
    slope_threshold_atr: float = 0.0

    @model_validator(mode="after")
    def _validate_periods(self) -> "StrategyConfig":
        if self.fast_ema <= 0:
            raise ValueError("fast_ema must be > 0")
        if self.slow_ema <= self.fast_ema:
            raise ValueError("slow_ema must be greater than fast_ema")
        return self

    @field_validator("angle_threshold", "angle_scale", "slope_threshold_atr")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("angle_lookback", "atr_period")
    @classmethod
    def _lookback_positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
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

    Input needs at least ``timestamp`` and ``close`` (plus ``high``/``low``
    when ``config.angle_mode == "atr_normalized"``, needed for ATR). Output
    is one row per input bar (HOLD rows included) with the fixed signal
    schema:

        timestamp, signal_type, crossover, ema_fast, ema_slow, angle, candle_close

    plus a trailing ``slope_atr`` column (null under ``angle_mode=
    "fixed_scale"``) -- appended, never inserted, so the original schema
    and every existing consumer (``Signal``, ``signal_events``, the MCP
    tools) is unaffected.
    """
    cfg = (
        StrategyConfig()
        if config is None
        else (config if isinstance(config, StrategyConfig) else StrategyConfig(**config))
    )
    if not {"timestamp", "close"}.issubset(frame.columns):
        raise ValueError("frame needs at least 'timestamp' and 'close' columns")

    fast, slow, angle_col = column_names(cfg)
    select_cols = [pl.col("timestamp"), pl.col("close")]
    if cfg.angle_mode == "atr_normalized":
        missing = [c for c in ("high", "low") if c not in frame.columns]
        if missing:
            raise ValueError(
                f"angle_mode='atr_normalized' requires columns {missing} "
                "(needed to compute ATR)"
            )
        select_cols += [pl.col("high"), pl.col("low")]

    work = frame.sort("timestamp").select(*select_cols)
    work = add_ema(work, cfg.fast_ema)
    work = add_ema(work, cfg.slow_ema)

    slope_atr_col = "_slope_atr"
    if cfg.angle_mode == "atr_normalized":
        work = add_atr(work, cfg.atr_period, name="_atr")
        work = add_ema_slope_atr(
            work, fast, atr_column="_atr", name=slope_atr_col, lookback=cfg.angle_lookback
        )
        # Schema stability: `angle` stays populated (in degrees, via atan)
        # even in ATR mode, so downstream consumers of the `angle` column
        # (Signal, signal_events, MCP tools) are unaffected either way.
        work = work.with_columns(
            (pl.col(slope_atr_col).arctan() * DEGREES_PER_RADIAN).alias(angle_col)
        )
    else:
        work = add_ema_angle(
            work, fast, name=angle_col, lookback=cfg.angle_lookback, scale=cfg.angle_scale
        )
        work = work.with_columns(pl.lit(None, dtype=pl.Float64).alias(slope_atr_col))

    f, s = pl.col(fast), pl.col(slow)
    prev_f, prev_s = f.shift(1), s.shift(1)
    crossover_up = (f > s) & (prev_f <= prev_s)
    crossover_down = (f < s) & (prev_f >= prev_s)

    close_gt_slow = pl.col("close") > pl.col(slow)
    if cfg.signal_mode == "crossover":
        base_buy, base_sell = crossover_up, crossover_down
    else:
        if cfg.angle_mode == "atr_normalized":
            slope = pl.col(slope_atr_col)
            gate_buy = slope >= cfg.slope_threshold_atr
            gate_sell = slope <= -cfg.slope_threshold_atr
        else:
            angle = pl.col(angle_col)
            gate_buy = angle >= cfg.angle_threshold
            gate_sell = angle <= -cfg.angle_threshold
        if cfg.signal_mode == "crossover_angle_and_trend":
            gate_buy = gate_buy & close_gt_slow
            gate_sell = gate_sell & (~close_gt_slow)
        signal_buy = crossover_up & gate_buy
        signal_sell = crossover_down & gate_sell
        base_buy, base_sell = signal_buy, signal_sell
    signal_type = (
        pl.when(base_buy)
        .then(pl.lit("BUY"))
        .when(base_sell)
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
            pl.col(slope_atr_col).alias("slope_atr"),
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


def _registry_generate_signals(frame: pl.DataFrame, params: dict[str, object]) -> pl.DataFrame:
    """Adapter: ``STRATEGY_REGISTRY``'s ``generate_signals(frame, params)``
    contract onto this module's ``generate_signals(frame, config=...)``.

    Registering the EMA family under the same registry as the 5 SMC
    strategies means it flows through the identical sweep/leaderboard
    machinery (``quant.research.sweep``) rather than a parallel path --
    one engine, one leaderboard schema, one gate, for every family.
    ``stop_price``/``target_price`` are always null: the EMA family uses
    ATR-based brackets (``ExitConfig(stop_mode="atr", ...)``), which
    never read these columns, unlike the SMC strategies' structural
    stops (``stop_mode="signal"``).
    """
    out = generate_signals(frame, config=StrategyConfig(**params))
    return out.with_columns(
        pl.lit(None, dtype=pl.Float64).alias("stop_price"),
        pl.lit(None, dtype=pl.Float64).alias("target_price"),
    )


from quant.strategies.base import StrategySpec, register_strategy  # noqa: E402

register_strategy(
    StrategySpec(
        id="ema",
        requires_volume=False,
        default_timeframes=("5m", "15m"),
        param_space={
            "fast_ema": (5, 8, 9, 13, 21),
            "slow_ema": (15, 21, 34, 55, 89),
            "angle_mode": ("atr_normalized",),
            "slope_threshold_atr": (0.0, 0.10, 0.20, 0.30, 0.45),
            "angle_lookback": (1, 3, 5),
            "signal_mode": ("crossover_and_angle", "crossover_angle_and_trend"),
        },
        generate_signals=_registry_generate_signals,
        description="9/15 EMA crossover with an ATR-normalized slope gate.",
    )
)
