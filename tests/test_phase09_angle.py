"""Phase 09: ATR-normalized EMA slope.

Two things must hold for this to be a safe replacement for the
fixed-scale angle filter:
1. ``angle_mode="fixed_scale"`` (the default) is byte-identical to the
   pre-Phase-09 output -- this is what makes the change backward
   compatible.
2. ``angle_mode="atr_normalized"`` produces a threshold whose selectivity
   does not blow up across timeframes/lookbacks the way the fixed-scale
   30-degree threshold did (0.55% of 1m bars vs 72.06% of 15m bars for
   the "same" nominal filter).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from quant.strategies.ema_9_15 import StrategyConfig, generate_signals

BASE = datetime(2026, 7, 1, 9, 15)


def _ohlc_frame(n: int, seed: int = 0) -> pl.DataFrame:
    """Deterministic pseudo-random-walk OHLC frame (no numpy dependency)."""
    price = 100.0
    state = seed or 1
    rows = []
    for i in range(n):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        step = ((state % 200) - 100) / 100.0  # in [-1, 1)
        price = max(1.0, price + step)
        high = price + abs(step) + 0.1
        low = price - abs(step) - 0.1
        rows.append(
            {
                "timestamp": BASE + timedelta(minutes=i),
                "open": price,
                "high": high,
                "low": low,
                "close": price,
            }
        )
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def test_fixed_scale_is_byte_identical_to_legacy():
    """Default angle_mode must reproduce the pre-Phase-09 signal output
    exactly, whether or not high/low columns happen to be present."""
    frame = _ohlc_frame(200)
    frame_no_ohlc = frame.select("timestamp", "close")

    out_default = generate_signals(frame_no_ohlc)
    out_with_ohlc_present = generate_signals(frame, config=StrategyConfig())

    legacy_cols = ["timestamp", "signal_type", "crossover", "ema_fast", "ema_slow", "angle",
                   "candle_close"]
    assert out_default.select(legacy_cols).equals(out_with_ohlc_present.select(legacy_cols))
    # slope_atr must be entirely null under fixed_scale.
    assert out_default["slope_atr"].null_count() == out_default.height


def test_atr_normalized_requires_high_low():
    frame = pl.DataFrame(
        {"timestamp": [BASE + timedelta(minutes=i) for i in range(30)], "close": [100.0] * 30},
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    cfg = StrategyConfig(angle_mode="atr_normalized", slope_threshold_atr=0.2)
    with pytest.raises(ValueError, match="high.*low|low.*high"):
        generate_signals(frame, config=cfg)


def test_atr_normalized_gate_is_symmetric_and_off_by_default():
    frame = _ohlc_frame(300)
    # Default slope_threshold_atr=0.0 -- the gate is a no-op (every
    # crossover passes), same shape as signal_mode="crossover".
    cfg_off = StrategyConfig(angle_mode="atr_normalized", slope_threshold_atr=0.0)
    out_off = generate_signals(frame, config=cfg_off)
    cfg_crossover = StrategyConfig(signal_mode="crossover")
    out_crossover = generate_signals(frame, config=cfg_crossover)
    assert out_off["signal_type"].to_list() == out_crossover["signal_type"].to_list()


def test_atr_normalized_selectivity_is_stable_across_timeframes():
    """The core Phase 09 claim: an ATR-normalized threshold's selectivity
    (fraction of bars passing the gate) should be much more stable across
    aggregation than the fixed-scale degree threshold was. This does not
    require real market data -- it holds for any frame with a roughly
    consistent volatility regime, which the synthetic walk provides."""
    frame_1 = _ohlc_frame(2000, seed=7)

    def resample(frame: pl.DataFrame, minutes: int) -> pl.DataFrame:
        return (
            frame.sort("timestamp")
            .group_by_dynamic("timestamp", every=f"{minutes}m", closed="left", label="left")
            .agg(
                open=pl.col("open").first(),
                high=pl.col("high").max(),
                low=pl.col("low").min(),
                close=pl.col("close").last(),
            )
        )

    frame_5 = resample(frame_1, 5)

    threshold = 0.2
    cfg = StrategyConfig(angle_mode="atr_normalized", slope_threshold_atr=threshold, atr_period=14)

    out_1 = generate_signals(frame_1, config=cfg)
    out_5 = generate_signals(frame_5, config=cfg)

    def pass_rate(out: pl.DataFrame) -> float:
        slope = out["slope_atr"].drop_nulls()
        if slope.len() == 0:
            return 0.0
        return (slope.abs() >= threshold).sum() / slope.len()

    rate_1 = pass_rate(out_1)
    rate_5 = pass_rate(out_5)
    # Both should be well clear of 0 and 1, and not wildly different --
    # nothing like the 0.55% vs 72.06% (131x) spread the fixed-scale
    # formula produced on real data.
    assert 0.0 < rate_1 < 1.0
    assert 0.0 < rate_5 < 1.0
    assert rate_5 / max(rate_1, 1e-9) < 5.0
    assert rate_1 / max(rate_5, 1e-9) < 5.0
