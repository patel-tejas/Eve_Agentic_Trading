"""Phase 04 unit tests: strategy engine signals.

Polars only; no network access. Verifies EMA math, crossover detection,
angle gating, seed handling, determinism and no look-ahead.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest
from pydantic import ValidationError

from quant.strategies.ema_9_15 import StrategyConfig, generate_signals, signal_events

BASE = datetime(2026, 7, 1, 9, 15)


def _frame(closes: list[float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "timestamp": [BASE + timedelta(minutes=i) for i in range(len(closes))],
            "close": closes,
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )


def test_config_defaults_and_validation():
    cfg = StrategyConfig()
    assert (cfg.fast_ema, cfg.slow_ema) == (9, 15)
    assert cfg.angle_threshold == 30.0
    assert cfg.angle_lookback == 1
    assert cfg.angle_scale == 1000.0
    with pytest.raises(ValidationError):
        StrategyConfig(fast_ema=15, slow_ema=9)
    with pytest.raises(ValidationError):
        StrategyConfig(angle_lookback=0)
    with pytest.raises(ValidationError):
        StrategyConfig(angle_threshold=-1.0)


def test_output_schema_and_determinism():
    closes = [100 + i for i in range(120)]
    out1 = generate_signals(_frame(closes))
    out2 = generate_signals(_frame(closes))
    assert out1.equals(out2)  # reproducible
    assert out1.columns == [
        "timestamp",
        "signal_type",
        "crossover",
        "ema_fast",
        "ema_slow",
        "angle",
        "candle_close",
    ]
    assert out1.height == 120
    assert set(out1["signal_type"].unique().to_list()) <= {"BUY", "SELL", "HOLD"}


def test_seed_window_is_hold():
    # First slow_ema-1 bars have no slow EMA -> HOLD even if later crosses
    closes = [100.0] * 5 + [200.0] * 100 + [50.0] * 60
    out = generate_signals(_frame(closes))
    head = out.head(14)
    assert (head["signal_type"] == "HOLD").all()
    assert head["ema_slow"].is_null().all()


def test_bullish_crossover_buy():
    # Flat -> step up: fast (9) EMA crosses slow (15) EMA upwards with a
    # steep enough angle to pass the threshold.
    closes = [100.0] * 60 + [101.0, 103.0, 106.0, 110.0, 115.0, 121.0, 128.0] + [130.0] * 30
    out = generate_signals(_frame(closes))
    buys = out.filter(pl.col("signal_type") == "BUY")
    assert buys.height >= 1
    row = buys.row(0)
    assert row[3] > row[4]  # ema_fast above ema_slow at the BUY bar
    assert row[5] >= 30.0  # angle gate


def test_near_flat_crossover_stays_hold():
    # Slow drift up the EMA lines without making a steep angle.
    closes = [100.0 + 0.5 * i for i in range(200)]
    out = generate_signals(_frame(closes))
    events = signal_events(out, timeframe="1m")
    assert events == []


def test_events_only_non_hold_and_sorted():
    closes = [100.0] * 60 + [101, 103, 106, 110, 115, 121, 128, 136, 145, 155, 166]
    out = generate_signals(_frame(closes))
    events = signal_events(out, timeframe="1m")
    assert all(e.signal_type in ("BUY", "SELL") for e in events)
    stamps = [e.timestamp for e in events]
    assert stamps == sorted(stamps)
    e = events[0]
    assert e.timeframe == "1m"
    assert e.crossover is True


def test_no_lookahead():
    # Signal at bar t must be identical to a run terminated at t.
    closes = [100.0] * 40 + [98, 97, 96, 95, 94] * 6 + [120.0] * 40
    full = generate_signals(_frame(closes))
    ser = full["signal_type"].to_list()
    for t in (19, 40, 60, 100):
        prefix = generate_signals(_frame(closes[: t + 1]))
        assert prefix["signal_type"][-1] == ser[t]


def test_config_dict_accepted():
    closes = [100.0] * 60 + [101, 104, 108, 113, 119, 126, 134]
    out = generate_signals(
        _frame(closes),
        config={"fast_ema": 9, "slow_ema": 15, "angle_threshold": 30.0},
    )
    assert "BUY" in out["signal_type"].to_list()
