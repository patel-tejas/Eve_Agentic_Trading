"""Phase 11: causality + correctness of the Heikin Ashi transform and the
candle-shape (doji/hammer) primitives.

Mirrors the discipline in ``tests/test_phase09_causality.py``: a value at
bar ``i`` must be identical whether computed on the full frame or on a
frame truncated to the first ``i+1`` bars. HA's ``ha_open`` is the one
recursive quantity here, seeded at bar 0 -- if the seed or the recursion
were wrong, this harness would still not catch it (both full and
truncated frames would agree, just be wrong the same way), so a
hand-computed 5-bar fixture checks the actual values too.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from quant.indicators.atr import add_atr
from quant.indicators.heikin_ashi import add_heikin_ashi
from quant.indicators.patterns import add_candle_shape

BASE = datetime(2026, 7, 1, 9, 15)


def _synthetic_frame(n: int = 300, seed: int = 7) -> pl.DataFrame:
    price = 100.0
    state = seed
    rows = []
    for i in range(n):
        ts = BASE + timedelta(minutes=i)
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        step = ((state % 400) - 200) / 100.0
        price = max(1.0, price + step)
        high = price + abs(step) + 0.5
        low = price - abs(step) - 0.5
        rows.append(
            {
                "timestamp": ts,
                "open": price - step * 0.4,
                "high": high,
                "low": low,
                "close": price,
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


def test_add_heikin_ashi_is_causal(frame):
    _assert_prefix_equals_full(
        add_heikin_ashi, frame, ["ha_open", "ha_high", "ha_low", "ha_close"]
    )


def test_add_candle_shape_is_causal_on_real_ohlc(frame):
    with_atr = add_atr(frame, 14, name="atr_14")

    def fn(f: pl.DataFrame) -> pl.DataFrame:
        return add_candle_shape(add_atr(f, 14, name="atr_14"), small_range_atr=0.8)

    _assert_prefix_equals_full(
        fn,
        with_atr,
        ["body", "range", "upper_wick", "lower_wick", "body_pct", "is_doji", "is_hammer",
         "is_inverted_hammer", "is_small_range"],
    )


def _add_ha_atr(f: pl.DataFrame, *, period: int = 14, name: str = "ha_atr_14") -> pl.DataFrame:
    """ATR computed on the HA high/low/close, without colliding with the
    frame's own real ``high``/``low`` columns (both a real and an HA pass
    can legitimately run against the same frame)."""
    ha_only = add_heikin_ashi(f).select(
        "timestamp", pl.col("ha_high").alias("high"), pl.col("ha_low").alias("low"),
        pl.col("ha_close").alias("close"),
    )
    atr_only = add_atr(ha_only, period, name=name).select("timestamp", name)
    return add_heikin_ashi(f).join(atr_only, on="timestamp", how="left")


def test_add_candle_shape_is_causal_on_heikin_ashi(frame):
    with_ha_atr = _add_ha_atr(frame)

    def fn(f: pl.DataFrame) -> pl.DataFrame:
        h_atr = _add_ha_atr(f)
        return add_candle_shape(h_atr, prefix="ha_", atr_column="ha_atr_14", small_range_atr=0.8)

    _assert_prefix_equals_full(
        fn,
        with_ha_atr,
        ["ha_body", "ha_range", "ha_upper_wick", "ha_lower_wick", "ha_body_pct",
         "ha_is_doji", "ha_is_hammer", "ha_is_inverted_hammer", "ha_is_small_range"],
    )


# ---------------------------------------------------------------------------
# Hand-computed 5-bar fixture -- proves the recursion AND its seed, not
# just that truncation agrees with itself.
# ---------------------------------------------------------------------------


def test_heikin_ashi_matches_hand_computed_values():
    rows = [
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0},
        {"open": 101.0, "high": 103.0, "low": 100.5, "close": 102.5},
        {"open": 102.5, "high": 102.8, "low": 100.0, "close": 100.5},
        {"open": 100.5, "high": 101.0, "low": 98.0, "close": 98.5},
        {"open": 98.5, "high": 100.0, "low": 97.5, "close": 99.8},
    ]
    frame = pl.DataFrame(
        {
            "timestamp": [BASE + timedelta(minutes=i) for i in range(5)],
            **{k: [r[k] for r in rows] for k in ("open", "high", "low", "close")},
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    out = add_heikin_ashi(frame).to_dicts()

    # ha_close[t] = mean(o,h,l,c)
    expected_ha_close = [sum(r.values()) / 4.0 for r in rows]
    for i, exp in enumerate(expected_ha_close):
        assert out[i]["ha_close"] == pytest.approx(exp)

    # ha_open[0] = (open[0] + close[0]) / 2 -- the textbook seed.
    expected_ha_open = [(rows[0]["open"] + rows[0]["close"]) / 2.0]
    for i in range(1, 5):
        expected_ha_open.append((expected_ha_open[i - 1] + expected_ha_close[i - 1]) / 2.0)
    for i, exp in enumerate(expected_ha_open):
        assert out[i]["ha_open"] == pytest.approx(exp)

    for i, r in enumerate(rows):
        assert out[i]["ha_high"] == pytest.approx(
            max(r["high"], expected_ha_open[i], expected_ha_close[i])
        )
        assert out[i]["ha_low"] == pytest.approx(
            min(r["low"], expected_ha_open[i], expected_ha_close[i])
        )


def test_doji_flag_on_a_near_zero_body_candle():
    frame = pl.DataFrame(
        {
            "timestamp": [BASE, BASE + timedelta(minutes=1)],
            "open": [100.0, 100.0],
            "high": [102.0, 102.0],
            "low": [98.0, 98.0],
            "close": [100.05, 101.9],  # bar 0: doji; bar 1: big body, not doji
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    out = add_candle_shape(frame, doji_body_pct=0.10).to_dicts()
    assert out[0]["is_doji"] is True
    assert out[1]["is_doji"] is False


def test_hammer_flag_requires_long_lower_wick_and_short_upper_wick():
    frame = pl.DataFrame(
        {
            "timestamp": [BASE, BASE + timedelta(minutes=1)],
            "open": [100.0, 100.0],
            "high": [100.2, 100.2],
            "low": [95.0, 95.0],
            "close": [100.0, 95.2],  # bar 0: hammer shape; bar 1: same body but no long lower wick
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    out = add_candle_shape(
        frame, hammer_body_pct=0.30, wick_ratio=0.55, opp_wick_ratio=0.20
    ).to_dicts()
    assert out[0]["is_hammer"] is True
    assert out[1]["is_hammer"] is False


def test_small_range_flag_gated_by_atr():
    frame = pl.DataFrame(
        {
            "timestamp": [BASE, BASE + timedelta(minutes=1)],
            "open": [100.0, 100.0],
            "high": [100.5, 110.0],
            "low": [99.5, 90.0],
            "close": [100.2, 100.0],
            "atr_14": [10.0, 10.0],
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    out = add_candle_shape(frame, small_range_atr=0.8).to_dicts()
    assert out[0]["is_small_range"] is True   # range=1.0 <= 0.8*10
    assert out[1]["is_small_range"] is False  # range=20.0 > 0.8*10


def test_small_range_disabled_when_zero():
    frame = pl.DataFrame(
        {
            "timestamp": [BASE],
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [100.0],
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    out = add_candle_shape(frame, small_range_atr=0.0).to_dicts()
    assert out[0]["is_small_range"] is True
