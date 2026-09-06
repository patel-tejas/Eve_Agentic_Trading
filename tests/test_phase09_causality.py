"""Phase 09: causality of every SMC structural primitive.

Non-negotiable. If only one test in this whole implementation gets
written, it is this one -- it mechanically catches the entire class of
lookahead bug that the reference SMC library (see
``quant/indicators/structure.py`` module docstring) has: a value at bar
``i`` must be identical whether it is computed on the full frame or on a
frame TRUNCATED to only the first ``i+1`` bars. If a primitive's value
at ``i`` changes once later bars are added, it was reading the future.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from quant.indicators.atr import add_atr
from quant.indicators.structure import (
    add_bos_choch,
    add_fvg,
    add_order_blocks,
    add_prev_day_levels,
    add_session_levels,
    add_swings,
    add_vwap,
)

BASE = datetime(2026, 7, 1, 9, 15)


def _synthetic_frame(n: int = 300, seed: int = 11) -> pl.DataFrame:
    """Deterministic multi-day OHLCV walk (no numpy/random dependency),
    with real intraday+overnight structure so day-boundary logic
    (PDH/PDL, opening range, VWAP reset) has something to bite on."""
    price = 100.0
    state = seed
    rows = []
    day_bar = 0
    day = 0
    for i in range(n):
        if day_bar >= 25:  # 25 bars/day, like a compact 15m session
            day_bar = 0
            day += 1
        ts = BASE + timedelta(days=day) + timedelta(minutes=15 * day_bar)
        day_bar += 1
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        step = ((state % 400) - 200) / 100.0  # in [-2, 2)
        price = max(1.0, price + step)
        high = price + abs(step) + 0.5
        low = price - abs(step) - 0.5
        vol = 100 + (state % 50)
        rows.append(
            {
                "timestamp": ts,
                "open": price,
                "high": high,
                "low": low,
                "close": price + step * 0.3,
                "volume": vol,
            }
        )
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


SAMPLED_FRACTIONS = (0.1, 0.25, 0.4, 0.55, 0.7, 0.85, 0.95)


def _sampled_indices(n: int) -> list[int]:
    return sorted({int(n * f) for f in SAMPLED_FRACTIONS if 0 < int(n * f) < n - 1})


def _assert_prefix_equals_full(fn, frame: pl.DataFrame, out_cols: list[str]) -> None:
    full = fn(frame)
    n = frame.height
    for i in _sampled_indices(n):
        truncated = fn(frame.head(i + 1))
        full_row = full.select(out_cols).row(i)
        trunc_row = truncated.select(out_cols).row(i)
        assert trunc_row == full_row, (
            f"{fn.__name__} at row {i}: full-frame={full_row} != "
            f"truncated-frame={trunc_row} -- this is a look-ahead bug"
        )


@pytest.fixture(scope="module")
def frame() -> pl.DataFrame:
    return _synthetic_frame()


def test_add_swings_is_causal(frame):
    _assert_prefix_equals_full(
        lambda f: add_swings(f, left=3, right=3),
        frame,
        ["swing_high_confirmed", "swing_high_level", "swing_low_confirmed", "swing_low_level"],
    )


def test_add_fvg_is_causal(frame):
    _assert_prefix_equals_full(
        add_fvg,
        frame,
        ["fvg_bullish", "fvg_bearish", "fvg_top", "fvg_bottom", "fvg_mitigated_this_bar"],
    )


def test_add_bos_choch_is_causal(frame):
    _assert_prefix_equals_full(
        lambda f: add_bos_choch(f, left=3, right=3),
        frame,
        ["bos", "choch", "structure_break_level", "structure_break_direction"],
    )


def test_add_order_blocks_is_causal(frame):
    with_atr = add_atr(frame, 14, name="atr")

    def fn(f: pl.DataFrame) -> pl.DataFrame:
        return add_order_blocks(add_atr(f, 14, name="atr"), displacement_atr_mult=0.5)

    _assert_prefix_equals_full(fn, with_atr, ["ob_bullish", "ob_bearish", "ob_top", "ob_bottom"])


def test_add_prev_day_levels_is_causal(frame):
    _assert_prefix_equals_full(add_prev_day_levels, frame, ["pdh", "pdl", "pdc"])


def test_add_session_levels_is_causal(frame):
    _assert_prefix_equals_full(
        lambda f: add_session_levels(f, start="09:15", end="09:45"),
        frame,
        ["or_high", "or_low"],
    )


def test_add_vwap_is_causal(frame):
    _assert_prefix_equals_full(add_vwap, frame, ["vwap", "vwap_is_proxy"])


def test_add_atr_is_causal(frame):
    _assert_prefix_equals_full(lambda f: add_atr(f, 14, name="atr"), frame, ["atr"])


# ---------------------------------------------------------------------------
# A deliberately BROKEN primitive, to prove the harness actually catches
# look-ahead when it is present (a vacuous test suite is worse than none).
# ---------------------------------------------------------------------------


def _lookahead_swing_high(f: pl.DataFrame, *, left: int = 3, right: int = 3) -> pl.DataFrame:
    """Intentionally wrong: emits the pivot AT p instead of at p+right --
    i.e. exactly the centred-window bug the real smartmoneyconcepts
    library has."""
    def _backward_max(col, window):
        return pl.col(col).shift(1).rolling_max(window_size=window, min_samples=window)

    def _forward_max(col, window):
        return (
            pl.col(col)
            .reverse()
            .shift(1)
            .rolling_max(window_size=window, min_samples=window)
            .reverse()
        )

    return f.with_columns(
        (
            (pl.col("high") > _backward_max("high", left))
            & (pl.col("high") > _forward_max("high", right))
        ).alias("swing_high_confirmed")
    )


def test_the_causality_harness_catches_a_real_lookahead_bug(frame):
    with pytest.raises(AssertionError):
        _assert_prefix_equals_full(_lookahead_swing_high, frame, ["swing_high_confirmed"])
