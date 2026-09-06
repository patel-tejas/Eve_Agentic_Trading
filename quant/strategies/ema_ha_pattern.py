"""HA-pattern-gated 9/15 EMA crossover ("ema_ha").

A new module, not an edit to ``quant.strategies.ema_9_15`` -- the
incumbent stays byte-identical so the existing campaign results
(``C2026-09-EMA-SMC``, rounds 1-4) remain directly comparable.

Entry logic, read off three annotated charts: buy/sell only on an EMA
crossover where the candle the cross forms on (or one of the
``pattern_window_bars`` candles before it) is a small-bodied Heikin Ashi
candle -- a hammer, inverted hammer, or doji, optionally also requiring
a small high-low range. The idea: a small HA body at a crossover means
the smoothed candle lost directional conviction right at the moment of
the cross, which is a real (causal) loss-of-momentum signal, not a
curve-fit parameter. See ``quant.indicators.heikin_ashi`` and
``quant.indicators.patterns`` for the primitives, and
``scripts/measure_ha_pattern_base_rate.py`` for the pre-registered base
rate this entry was checked against before this file was written.

Stops are STRUCTURAL, not ATR-multiples: the low (long) / high (short)
of the "anchor" bar -- the signal bar itself, or the most recent
pattern-qualifying bar within the window, per ``stop_anchor`` -- always
read from REAL OHLC by default (``stop_reference="real"``, tradeable),
with an opt-in ``"ha"`` mode for comparison against the smoothed level
the chart actually shows. Emitted via the standard ``stop_price``
column and consumed by ``ExitConfig(stop_mode="signal")`` -- exactly
the same path the 5 SMC strategies use; no engine change is needed for
the stop itself. ``target_price`` stays null: the scale-out ladder
(``ExitConfig.scale_out``, see ``quant.backtest.exits``) replaces a
single fixed target.
"""

from __future__ import annotations

from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, field_validator, model_validator

from quant.indicators.atr import add_atr
from quant.indicators.ema import add_ema
from quant.indicators.heikin_ashi import add_heikin_ashi
from quant.indicators.patterns import add_candle_shape
from quant.strategies._common import finalize_signals
from quant.strategies.base import StrategySpec, register_strategy

STRATEGY_ID = "ema_ha"

PatternSet = Literal["any", "doji_only", "directional"]
StopAnchor = Literal["pattern_bar", "signal_bar"]
StopReference = Literal["real", "ha"]


class StrategyConfig(BaseModel):
    """Frozen strategy parameters. Every default reproduces a plain,
    unfiltered crossover with pattern_set='any' at maximum permissiveness
    where possible, but there is no fully neutral "gate off" state here
    (unlike ``ema_9_15``'s ``slope_threshold_atr=0.0``) -- the HA pattern
    filter is this strategy's entire premise, not an optional extra."""

    fast_ema: int = 9
    slow_ema: int = 15

    pattern_window_bars: int = 0  # 0 = literal "on the crossover candle itself"
    pattern_set: PatternSet = "any"
    doji_body_pct: float = 0.20
    hammer_body_pct: float = 0.30
    wick_ratio: float = 0.55
    opp_wick_ratio: float = 0.20
    small_range_atr: float = 0.0  # 0.0 disables the range check

    atr_period: int = 14
    slope_threshold_atr: float = 0.0  # 0.0 = the extra trend/slope gate is off

    stop_anchor: StopAnchor = "pattern_bar"
    stop_reference: StopReference = "real"
    stop_buffer_atr: float = 0.0

    @model_validator(mode="after")
    def _validate(self) -> "StrategyConfig":
        if self.fast_ema <= 0:
            raise ValueError("fast_ema must be > 0")
        if self.slow_ema <= self.fast_ema:
            raise ValueError("slow_ema must be greater than fast_ema")
        if not 0 <= self.pattern_window_bars <= 3:
            raise ValueError("pattern_window_bars must be in [0, 3]")
        return self

    @field_validator(
        "doji_body_pct", "hammer_body_pct", "wick_ratio", "opp_wick_ratio",
        "small_range_atr", "slope_threshold_atr", "stop_buffer_atr",
    )
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("must be >= 0")
        return v

    @field_validator("atr_period")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 1:
            raise ValueError("must be >= 1")
        return v


def _prepare(frame: pl.DataFrame, cfg: StrategyConfig) -> pl.DataFrame:
    """Attach EMA/ATR/HA/pattern columns. Everything here is causal: EMA
    and ATR are standard causal rolling constructs, HA is causal by
    construction (see ``quant.indicators.heikin_ashi``), and the pattern
    flags depend only on each bar's own OHLC/HA values."""
    work = frame.sort("timestamp")
    work = add_ema(work, cfg.fast_ema)
    work = add_ema(work, cfg.slow_ema)
    work = add_atr(work, cfg.atr_period, name="_atr")
    work = add_heikin_ashi(work)

    # ATR computed on the HA high/low/close, joined back in under its own
    # name so it never collides with the real `_atr` column above -- both
    # a real-OHLC and an HA pass over add_candle_shape can legitimately
    # run against the same frame.
    ha_for_atr = work.select(
        "timestamp",
        pl.col("ha_high").alias("high"),
        pl.col("ha_low").alias("low"),
        pl.col("ha_close").alias("close"),
    )
    ha_atr = add_atr(ha_for_atr, cfg.atr_period, name="_ha_atr").select("timestamp", "_ha_atr")
    work = work.join(ha_atr, on="timestamp", how="left")

    work = add_candle_shape(
        work,
        prefix="ha_",
        atr_column="_ha_atr",
        doji_body_pct=cfg.doji_body_pct,
        hammer_body_pct=cfg.hammer_body_pct,
        wick_ratio=cfg.wick_ratio,
        opp_wick_ratio=cfg.opp_wick_ratio,
        small_range_atr=cfg.small_range_atr,
    )
    return work


def generate_signals(frame: pl.DataFrame, params: dict[str, Any]) -> pl.DataFrame:
    """Registry-contract entry point: one row per bar, BUY/SELL fires on
    a qualifying crossover, ``stop_price`` set structurally, ``target_price``
    always null (the scale-out ladder in ``ExitConfig`` owns exits)."""
    cfg = StrategyConfig(**params)
    work = _prepare(frame, cfg)

    fast, slow = pl.col(f"ema_{cfg.fast_ema}"), pl.col(f"ema_{cfg.slow_ema}")
    prev_fast, prev_slow = fast.shift(1), slow.shift(1)
    crossover_up = (fast > slow) & (prev_fast <= prev_slow)
    crossover_down = (fast < slow) & (prev_fast >= prev_slow)

    if cfg.pattern_set == "doji_only":
        qualifies_buy = pl.col("ha_is_doji")
        qualifies_sell = pl.col("ha_is_doji")
    elif cfg.pattern_set == "directional":
        qualifies_buy = pl.col("ha_is_doji") | pl.col("ha_is_hammer")
        qualifies_sell = pl.col("ha_is_doji") | pl.col("ha_is_inverted_hammer")
    else:  # "any"
        any_pattern = (
            pl.col("ha_is_doji") | pl.col("ha_is_hammer") | pl.col("ha_is_inverted_hammer")
        )
        qualifies_buy = any_pattern
        qualifies_sell = any_pattern
    qualifies_buy = qualifies_buy & pl.col("ha_is_small_range")
    qualifies_sell = qualifies_sell & pl.col("ha_is_small_range")

    w = cfg.pattern_window_bars
    # Trailing "was true within the last w bars, including this one" --
    # window is small (<=3) so an explicit shift-and-OR is fully
    # vectorised and trivially causal (each term only reads bars <= t).
    def _in_window(flag: pl.Expr) -> pl.Expr:
        expr = flag.fill_null(False)
        for k in range(1, w + 1):
            expr = expr | flag.shift(k).fill_null(False)
        return expr

    buy_qualifies_window = _in_window(qualifies_buy)
    sell_qualifies_window = _in_window(qualifies_sell)

    if cfg.slope_threshold_atr > 0.0:
        slope = (fast - fast.shift(1)) / pl.col("_atr")
        slope_gate_buy = slope >= cfg.slope_threshold_atr
        slope_gate_sell = slope <= -cfg.slope_threshold_atr
    else:
        slope_gate_buy = pl.lit(True)
        slope_gate_sell = pl.lit(True)

    signal_buy = crossover_up & buy_qualifies_window & slope_gate_buy
    signal_sell = crossover_down & sell_qualifies_window & slope_gate_sell

    signal_type = (
        pl.when(signal_buy).then(pl.lit("BUY")).when(signal_sell).then(pl.lit("SELL"))
        .otherwise(pl.lit("HOLD"))
    )

    # Structural stop anchor: the low (buy) / high (sell) of whichever
    # bar in [t-w, t] most recently qualified, coalescing from the most
    # recent (shift 0) backward -- `pattern_bar`. `signal_bar` just uses
    # bar t's own extreme, i.e. the w=0 case of the same coalesce.
    low_col = "ha_low" if cfg.stop_reference == "ha" else "low"
    high_col = "ha_high" if cfg.stop_reference == "ha" else "high"

    if cfg.stop_anchor == "signal_bar":
        anchor_low = pl.col(low_col)
        anchor_high = pl.col(high_col)
    else:
        masked_low = pl.when(qualifies_buy).then(pl.col(low_col)).otherwise(None)
        masked_high = pl.when(qualifies_sell).then(pl.col(high_col)).otherwise(None)
        anchor_low = pl.coalesce([masked_low.shift(k) for k in range(0, w + 1)])
        anchor_high = pl.coalesce([masked_high.shift(k) for k in range(0, w + 1)])
        # Fallback to the signal bar's own extreme if, for some reason,
        # no qualifying bar's low/high resolved (should not happen given
        # buy_qualifies_window/sell_qualifies_window gated the signal,
        # but never leave a BUY/SELL with a null stop).
        anchor_low = anchor_low.fill_null(pl.col(low_col))
        anchor_high = anchor_high.fill_null(pl.col(high_col))

    stop_price = (
        pl.when(signal_buy)
        .then(anchor_low - cfg.stop_buffer_atr * pl.col("_atr"))
        .when(signal_sell)
        .then(anchor_high + cfg.stop_buffer_atr * pl.col("_atr"))
        .otherwise(None)
    )

    out = work.with_columns(
        signal_type.alias("signal_type"),
        stop_price.alias("stop_price"),
        pl.lit(None, dtype=pl.Float64).alias("target_price"),
    )

    return finalize_signals(
        out,
        out["signal_type"].to_list(),
        out["stop_price"].to_list(),
        out["target_price"].to_list(),
    )


PARAM_SPACE: dict[str, tuple[Any, ...]] = {
    "fast_ema": (5, 9, 13),
    "slow_ema": (15, 21, 34),
    "pattern_window_bars": (0, 1, 2, 3),
    "pattern_set": ("any", "doji_only", "directional"),
    "doji_body_pct": (0.10, 0.20, 0.30),
    "wick_ratio": (0.40, 0.55),
    "small_range_atr": (0.0, 0.8, 1.2),
    "slope_threshold_atr": (0.0, 0.15),
}

register_strategy(
    StrategySpec(
        id=STRATEGY_ID,
        requires_volume=False,
        default_timeframes=("5m", "15m"),
        param_space=PARAM_SPACE,
        generate_signals=generate_signals,
        description=(
            "9/15 EMA crossover gated on a Heikin-Ashi doji/hammer/inverted-hammer "
            "pattern at (or just before) the cross; structural stop at the anchor "
            "bar's real low/high; paired with ExitConfig.scale_out for the exit ladder."
        ),
    )
)
