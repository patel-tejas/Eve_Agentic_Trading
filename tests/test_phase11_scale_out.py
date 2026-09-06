"""Phase 11: partial scale-out exit ladder.

``ExitConfig(scale_out=())`` (the default) must reproduce every existing
Phase 05/09 test byte-for-bit -- that equivalence is exercised by the
untouched test_phase05_backtest.py / test_phase09_exits.py suites
themselves (see quant.backtest.engine's module docstring), not repeated
here. This file exercises the NEW mechanics: lot quantisation, multi-leg
consolidation into one trades-frame row, intrabar precedence with legs,
breakeven-after-leg-1, and the prev-candle-extreme trail -- each with a
named test that guards a specific way this could silently manufacture
fake profit or silently corrupt the trade count.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import polars as pl
import pytest

from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.exits import ExitConfig, ScaleLeg

BASE = datetime(2026, 7, 1, 9, 15)


def _ohlc(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def _flat_candles(n: int, price: float = 100.0, *, start: datetime = BASE) -> list[dict]:
    return [
        {
            "timestamp": start + timedelta(minutes=i),
            "open": price,
            "high": price + 0.5,
            "low": price - 0.5,
            "close": price,
        }
        for i in range(n)
    ]


def _signals(n: int, buy_at: int | None = None, sell_at: int | None = None, *, start=BASE):
    types = ["HOLD"] * n
    if buy_at is not None:
        types[buy_at] = "BUY"
    if sell_at is not None:
        types[sell_at] = "SELL"
    return pl.DataFrame(
        {"timestamp": [start + timedelta(minutes=i) for i in range(n)], "signal_type": types},
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )


# ---------------------------------------------------------------------------
# ScaleLeg validation
# ---------------------------------------------------------------------------


def test_scale_leg_rejects_non_positive_at_r():
    with pytest.raises(ValueError, match="at_r"):
        ScaleLeg(at_r=0.0, fraction=0.5)


def test_scale_leg_rejects_out_of_range_fraction():
    with pytest.raises(ValueError, match="fraction"):
        ScaleLeg(at_r=1.0, fraction=1.5)


# ---------------------------------------------------------------------------
# Lot quantisation
# ---------------------------------------------------------------------------


def test_scale_out_raises_when_a_leg_quantises_to_zero_lots():
    """position_size=1 with a 50/25/25 ladder cannot be expressed in whole
    lots -- must raise loudly, never silently trade a partial ladder."""
    rows = _flat_candles(30)
    candles = _ohlc(rows)
    signals = _signals(30, buy_at=5)
    cfg = BacktestConfig(
        position_size=1,
        exits=ExitConfig(
            stop_mode="points",
            stop_points=10.0,
            scale_out=(ScaleLeg(at_r=1.0, fraction=0.5), ScaleLeg(at_r=2.0, fraction=0.25)),
        ),
    )
    with pytest.raises(ValueError, match="quantises to 0"):
        run_backtest(candles, signals, cfg)


def test_scale_out_legs_sum_exceeding_position_size_raises():
    rows = _flat_candles(30)
    candles = _ohlc(rows)
    signals = _signals(30, buy_at=5)
    cfg = BacktestConfig(
        position_size=4,
        exits=ExitConfig(
            stop_mode="points",
            stop_points=10.0,
            scale_out=(ScaleLeg(at_r=1.0, fraction=0.75), ScaleLeg(at_r=2.0, fraction=0.75)),
        ),
    )
    with pytest.raises(ValueError, match="exceeding"):
        run_backtest(candles, signals, cfg)


# ---------------------------------------------------------------------------
# Multi-leg consolidation: N legs -> exactly 1 trades-frame row.
# ---------------------------------------------------------------------------


def test_three_legs_produce_one_trade_row_with_full_quantity():
    """4 lots, 50/25/25 ladder (2/1/1 lots). A steadily rising market
    should fill all three legs (1R, 2R, then the runner trailing) and
    STILL emit exactly one trades-frame row with the ORIGINAL full
    quantity -- never 3 rows, which would triple total_trades and corrupt
    every downstream metric and the pre-registered MIN_TRADES gate."""
    n = 40
    rows = _flat_candles(n, price=100.0)
    # Stop 2 points below entry (fills at bar 10 open=100 -> entry ~100).
    # Risk = 2 -> leg1 at 1R = 102, leg2 at 2R = 104. Ramp price up steadily
    # so both legs, then the runner (trailing), all fill in sequence.
    for i in range(11, n):
        bump = (i - 10) * 0.5
        rows[i] = {
            **rows[i],
            "open": 100.0 + bump,
            "high": 100.5 + bump,
            "low": 99.5 + bump,
            "close": 100.0 + bump,
        }
    candles = _ohlc(rows)
    signals = _signals(n, buy_at=10)
    cfg = BacktestConfig(
        position_size=4,
        lot_size=65,
        exits=ExitConfig(
            stop_mode="points",
            stop_points=2.0,
            scale_out=(ScaleLeg(at_r=1.0, fraction=0.50), ScaleLeg(at_r=2.0, fraction=0.25)),
            trail_mode="prev_candle_extreme",
            trail_after_leg=2,
            eod_squareoff="15:29",
        ),
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert len(trades) == 1
    assert trades[0]["quantity"] == 4 * 65
    assert trades[0]["n_legs"] == 3
    legs = json.loads(trades[0]["exit_legs_json"])
    assert len(legs) == 3
    assert sum(leg["qty"] for leg in legs) == 4 * 65
    assert legs[0]["qty"] == 2 * 65  # 50% leg
    assert legs[1]["qty"] == 1 * 65  # 25% leg
    assert legs[2]["qty"] == 1 * 65  # runner


def test_leg_costs_equal_one_entry_order_plus_n_exit_orders():
    """Regression guard against the specific bug the plan calls out:
    calling round_trip_costs PER LEG would charge the entry brokerage N
    times. Costs must be exactly cost_of_order(entry, full_qty) once,
    plus cost_of_order(leg_price, leg_qty) once per leg."""
    from quant.backtest.costs import CostConfig, cost_of_order

    n = 30
    rows = _flat_candles(n, price=100.0)
    rows[11] = {**rows[11], "open": 102.0, "high": 102.5, "low": 101.5, "close": 102.0}
    for i in range(12, n):
        rows[i] = {**rows[i], "open": 102.0, "high": 102.5, "low": 101.5, "close": 102.0}
    candles = _ohlc(rows)
    signals = _signals(n, buy_at=10)
    cost_cfg = CostConfig()
    cfg = BacktestConfig(
        position_size=2,
        lot_size=65,
        costs=cost_cfg,
        exits=ExitConfig(
            stop_mode="points",
            stop_points=5.0,
            scale_out=(ScaleLeg(at_r=1.0, fraction=1.0),),
            eod_squareoff="15:29",
        ),
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert len(trades) == 1
    entry_price = trades[0]["entry_price"]
    legs = json.loads(trades[0]["exit_legs_json"])
    assert len(legs) == 1
    expected = cost_of_order(entry_price, 2 * 65, "buy", cost_cfg) + cost_of_order(
        legs[0]["price"], 2 * 65, "sell", cost_cfg
    )
    assert trades[0]["costs"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Intrabar precedence with legs
# ---------------------------------------------------------------------------


def test_stop_wins_over_a_scale_leg_in_the_same_bar():
    """If the stop AND a scale-out leg's level are both inside the same
    bar, the stop closes the ENTIRE remaining position -- it must not
    partially fill the leg first."""
    n = 20
    rows = _flat_candles(n, price=100.0)
    # bar 11: entry fill bar. bar 12 breaches BOTH the 2-point stop (low)
    # and the 1R=2-point target (high) in the same bar.
    rows[12] = {**rows[12], "open": 100.0, "high": 104.0, "low": 96.0, "close": 100.0}
    candles = _ohlc(rows)
    signals = _signals(n, buy_at=10)
    cfg = BacktestConfig(
        position_size=2,
        lot_size=65,
        exits=ExitConfig(
            stop_mode="points",
            stop_points=2.0,
            scale_out=(ScaleLeg(at_r=1.0, fraction=1.0),),
        ),
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert trades[0]["exit_reason"] == "stop"
    assert trades[0]["n_legs"] == 1
    assert trades[0]["quantity"] == 2 * 65


def test_gap_through_a_leg_target_fills_at_the_open():
    n = 20
    rows = _flat_candles(n, price=100.0)
    # bar 12 gaps open straight past the 1R=102 level.
    rows[12] = {**rows[12], "open": 106.0, "high": 106.5, "low": 105.5, "close": 106.0}
    candles = _ohlc(rows)
    signals = _signals(n, buy_at=10)
    cfg = BacktestConfig(
        position_size=4,
        lot_size=65,
        exits=ExitConfig(
            stop_mode="points",
            stop_points=2.0,
            scale_out=(ScaleLeg(at_r=1.0, fraction=0.5),),
        ),
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    legs = json.loads(trades[0]["exit_legs_json"])
    assert legs[0]["price"] == pytest.approx(106.0)  # filled at the gapped open, not at 102


# ---------------------------------------------------------------------------
# Breakeven-after-leg-1: never on the fill bar itself.
# ---------------------------------------------------------------------------


def test_breakeven_after_leg1_not_effective_on_the_fill_bar_itself():
    """Leg 1 fills on some bar. That SAME bar must not also stop out the
    runner at the newly-armed breakeven level -- the move is only
    effective starting the NEXT bar (mirrors the trailing-stop
    causality guard one section up)."""
    n = 30
    rows = _flat_candles(n, price=100.0)
    # bar 11: entry fill (open=100). bar 13: price reaches 1R=102 (leg1
    # fill) AND -- if breakeven fired on this same bar -- would also dip
    # back to entry_price=100 in the SAME bar's range, which must NOT
    # close the runner today.
    rows[13] = {**rows[13], "open": 100.0, "high": 102.5, "low": 99.5, "close": 101.0}
    # bar 14: price actually returns to entry -- the runner MUST stop out
    # here, once breakeven is legitimately armed (i >= breakeven_from_bar).
    rows[14] = {**rows[14], "open": 101.0, "high": 101.2, "low": 99.0, "close": 99.5}
    candles = _ohlc(rows)
    signals = _signals(n, buy_at=10)
    cfg = BacktestConfig(
        position_size=4,
        lot_size=65,
        exits=ExitConfig(
            stop_mode="points",
            stop_points=2.0,
            scale_out=(ScaleLeg(at_r=1.0, fraction=0.5),),
            after_leg1_stop="breakeven",
        ),
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    legs = json.loads(trades[0]["exit_legs_json"])
    assert len(legs) == 2
    assert legs[0]["reason"] == "target"  # leg 1, at bar 13
    assert legs[1]["reason"] == "stop"  # runner, breakeven stop at bar 14 (NOT bar 13)
    assert legs[1]["time"] == rows[14]["timestamp"].isoformat()
    assert legs[1]["price"] == pytest.approx(100.0)  # entry price (breakeven)


# ---------------------------------------------------------------------------
# prev_candle_extreme trail: bar i uses low[i-1]/high[i-1], never bar i's own.
# ---------------------------------------------------------------------------


def _staircase_candles(n: int, *, start: datetime = BASE) -> list[dict]:
    """Gently rising lows (never flat -- a flat fixture makes prev_low
    equal the current bar's own low on every bar, which cannot
    distinguish 'uses bar i-1' from 'uses bar i'). Open/high/close track
    the same staircase so every bar is internally consistent."""
    rows = []
    for i in range(n):
        low = 90.0 + i * 0.01
        rows.append(
            {
                "timestamp": start + timedelta(minutes=i),
                "open": low + 0.3,
                "high": low + 0.6,
                "low": low,
                "close": low + 0.3,
            }
        )
    return rows


def test_prev_candle_extreme_trail_uses_prior_bar_low_not_current_bars():
    """Bar 15 makes a big, anomalous UP-thrust (own low far ABOVE the
    staircase). If the trail illegally used bar i's OWN low (instead of
    i-1's), it would tighten the stop to bar 15's own low and then
    check bar 15's own (identical) low against it -- stopping out bar 15
    against its own same-bar data. Correctly, only bar 16 -- once bar 15
    is legitimately `i-1` -- may react to that high floor, and bar 16's
    own (normal, staircase-level) low is what trips it."""
    n = 30
    rows = _staircase_candles(n)
    rows[15] = {**rows[15], "open": 116.0, "high": 116.5, "low": 115.0, "close": 115.5}
    candles = _ohlc(rows)
    signals = _signals(n, buy_at=10)
    cfg = BacktestConfig(
        position_size=1,
        lot_size=65,
        exits=ExitConfig(
            stop_mode="points",
            stop_points=500.0,  # far away -- never the thing that fires on its own
            scale_out=(ScaleLeg(at_r=100.0, fraction=1.0),),  # never reachable -- trail-only exit
            trail_mode="prev_candle_extreme",
            trail_buffer_atr=0.0,
        ),
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert trades[0]["exit_time"] != rows[15]["timestamp"]
    assert trades[0]["exit_time"] == rows[16]["timestamp"]
    assert trades[0]["exit_reason"] == "stop"
