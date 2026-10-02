"""Phase 15 P1: no compiled spec can look ahead.

For every indicator, comparator, level and change reference: signals computed
on a truncated history must equal the same bars' signals computed on the full
history. If any operand peeked at a future bar, truncation would change an
earlier signal.
"""

from __future__ import annotations

import pytest

from quant.strategies.spec import analyse, spec_signals
from tests._spec_fixtures import cond, const, ind, intraday_candles

PRICE = {"kind": "price", "field": "close"}


def _long(entry: list[dict]) -> dict:
    return {
        "name": "causality",
        "timeframe": "15m",
        "direction": "long_only",
        "entry": {"long": {"all": entry}},
        "exit": {"long": {"any": [cond(PRICE, "lt", ind("sma", period=4))]}},
        "risk": {"stop": {"mode": "atr", "value": 2}},
    }


CASES = {
    "ema_cross": [cond(ind("ema", period=5), "crosses_above", ind("ema", period=13))],
    "sma_cross_below": [cond(ind("sma", period=5), "crosses_below", ind("sma", period=20))],
    "rsi": [cond(ind("rsi", period=7), "lt", const(40))],
    "macd_signal": [cond(ind("macd", output="line", fast=5, slow=13, signal=4), "crosses_above",
                         ind("macd", output="signal", fast=5, slow=13, signal=4))],
    "macd_hist": [cond(ind("macd", output="hist"), "gte", const(0))],
    "bbands": [cond(PRICE, "lte", ind("bbands", output="lower", period=10, stddev=1.5))],
    "atr": [cond(ind("atr", period=7), "gt", const(15))],
    "ema_angle": [cond(ind("ema_angle", period=9, lookback=2), "gt", const(20))],
    "offset": [cond(PRICE, "gt", {"kind": "price", "field": "high", "offset": 3})],
    "rising": [cond(ind("ema", period=8), "rising", bars=3)],
    "falling": [cond(ind("rsi", period=10), "falling", bars=2)],
    "prev_day": [cond(PRICE, "crosses_above", {"kind": "level", "name": "prev_day_high"})],
    "session_levels": [cond(PRICE, "gte", {"kind": "level", "name": "session_high"}),
                       cond(PRICE, "gt", {"kind": "level", "name": "session_open"})],
    "session_low": [cond(PRICE, "lte", {"kind": "level", "name": "session_low", "offset": 1})],
    "vwap": [cond(PRICE, "crosses_above", {"kind": "level", "name": "vwap"})],
    "change_pct": [cond({"kind": "change_pct", "ref": "prev_day_close"}, "lt", const(-0.3))],
    "change_open": [cond({"kind": "change_pct", "ref": "session_open"}, "gt", const(0.2))],
    "change_bar": [cond({"kind": "change_pct", "ref": "prev_bar_close"}, "gte", const(0.05))],
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_truncating_the_future_never_changes_past_signals(name: str) -> None:
    candles = intraday_candles(days=12)
    spec = analyse(_long(CASES[name])).require_valid()
    full = spec_signals(candles, spec)["signal_type"].to_list()
    assert any(s != "HOLD" for s in full), "case never fires; it proves nothing"
    for cut in (40, 97, 150, 233, candles.height - 7):
        part = spec_signals(candles.head(cut), spec)["signal_type"].to_list()
        assert part == full[:cut], f"{name}: signal changed when bars after {cut} were removed"
