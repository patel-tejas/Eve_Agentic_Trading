"""Phase 09: MarketContext unit conversion guard.

The instrument metadata on disk reports tick_size in PAISE (10.0 = Rs
0.10). MarketContext is the single conversion boundary; these tests make
sure a raw paise value can never reach the backtest engine unconverted.
"""

from __future__ import annotations

import polars as pl
import pytest

from quant.backtest.market import MarketContext, market_context_from_candles


def test_raw_paise_value_is_rejected():
    with pytest.raises(ValueError, match="paise"):
        MarketContext(
            symbol="NIFTY", price_source="futures", lot_size=65, tick_size_rupees=10.0
        )


def test_correct_rupee_value_is_accepted():
    ctx = MarketContext(
        symbol="NIFTY", price_source="futures", lot_size=65, tick_size_rupees=0.10
    )
    assert ctx.lot_size == 65
    assert ctx.tick_size_rupees == pytest.approx(0.10)


def test_lot_size_not_scaled():
    ctx = MarketContext(
        symbol="BANKNIFTY", price_source="futures", lot_size=15, tick_size_rupees=0.05
    )
    assert ctx.lot_size == 15  # a count, never divided/multiplied


def test_non_positive_lot_size_rejected():
    with pytest.raises(ValueError):
        MarketContext(symbol="X", price_source="futures", lot_size=0, tick_size_rupees=0.05)


def test_market_context_from_candles_converts_paise_to_rupees():
    frame = pl.DataFrame(
        {
            "lot_size": [65, 65, 65],
            "tick_size": [10.0, 10.0, 10.0],  # paise, matching contract_metadata.json
        }
    )
    ctx = market_context_from_candles(frame, symbol="NIFTY", price_source="futures")
    assert ctx.lot_size == 65
    assert ctx.tick_size_rupees == pytest.approx(0.10)


def test_market_context_from_candles_rejects_multiple_values():
    frame = pl.DataFrame({"lot_size": [65, 50], "tick_size": [10.0, 10.0]})
    with pytest.raises(ValueError):
        market_context_from_candles(frame, symbol="NIFTY")


def test_market_context_from_candles_requires_columns():
    frame = pl.DataFrame({"close": [1.0, 2.0]})
    with pytest.raises(ValueError):
        market_context_from_candles(frame, symbol="NIFTY")
