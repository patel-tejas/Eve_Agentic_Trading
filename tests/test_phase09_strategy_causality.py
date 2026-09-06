"""Phase 09: causality of every registered strategy's generate_signals.

Same guarantee as tests/test_phase09_causality.py, applied one level up:
a strategy's signal at bar i (signal_type, stop_price, target_price) must
be identical whether computed on the full frame or on a frame truncated
to the first i+1 bars. This is what makes it safe to run these
strategies inside a walk-forward/rolling backtest at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

# Importing these modules registers them into STRATEGY_REGISTRY. Imported
# explicitly here (not relied on via another test file's import order at
# collection time) so this file's parametrization is deterministic
# regardless of test collection/run order.
import quant.strategies.ema_9_15  # noqa: F401
import quant.strategies.ist_judas  # noqa: F401
import quant.strategies.orb_vwap  # noqa: F401
import quant.strategies.pdh_pdl_turtle_soup  # noqa: F401
import quant.strategies.smc_ob_choch  # noqa: F401
import quant.strategies.smc_sweep_fvg  # noqa: F401
from quant.strategies.base import STRATEGY_REGISTRY

BASE = datetime(2026, 7, 1, 9, 15)


def _synthetic_frame(n: int = 500, seed: int = 23, bars_per_day: int = 25) -> pl.DataFrame:
    price = 100.0
    state = seed
    rows = []
    day_bar = 0
    day = 0
    for i in range(n):
        if day_bar >= bars_per_day:
            day_bar = 0
            day += 1
        ts = BASE + timedelta(days=day) + timedelta(minutes=15 * day_bar)
        day_bar += 1
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        step = ((state % 400) - 200) / 100.0
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


SAMPLED_FRACTIONS = (0.15, 0.3, 0.45, 0.6, 0.75, 0.9)


def _sampled_indices(n: int) -> list[int]:
    return sorted({int(n * f) for f in SAMPLED_FRACTIONS if 0 < int(n * f) < n - 1})


@pytest.fixture(scope="module")
def frame() -> pl.DataFrame:
    return _synthetic_frame()


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_REGISTRY))
def test_strategy_signals_are_causal(strategy_id: str, frame: pl.DataFrame):
    spec = STRATEGY_REGISTRY[strategy_id]
    params: dict = {}
    full = spec.generate_signals(frame, params)
    n = frame.height
    out_cols = ["signal_type", "stop_price", "target_price"]
    for i in _sampled_indices(n):
        truncated = spec.generate_signals(frame.head(i + 1), params)
        full_row = full.select(out_cols).row(i)
        trunc_row = truncated.select(out_cols).row(i)
        assert trunc_row == full_row, (
            f"{strategy_id} at row {i}: full-frame={full_row} != "
            f"truncated-frame={trunc_row} -- this is a look-ahead bug"
        )


@pytest.mark.parametrize("strategy_id", sorted(STRATEGY_REGISTRY))
def test_strategy_output_schema(strategy_id: str, frame: pl.DataFrame):
    spec = STRATEGY_REGISTRY[strategy_id]
    out = spec.generate_signals(frame, {})
    assert out.height == frame.height
    assert {"timestamp", "signal_type", "stop_price", "target_price"}.issubset(out.columns)
    assert set(out["signal_type"].unique().to_list()) <= {"BUY", "SELL", "HOLD"}
