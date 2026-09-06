"""Phase 09: bracket exits.

Default ``ExitConfig()`` must reproduce the Phase 05 engine's behaviour
bit-for-bit (this is what makes the change backward compatible and is
why none of the 13 pre-existing test files needed to change). Everything
else here exercises the new bracket mechanics: intrabar precedence
(stop wins ties, gaps fill at the open), the trailing stop's strict
"only bars <= i-1" rule, wall-clock EOD square-off, and schema stability.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from quant.backtest.engine import BacktestConfig, run_backtest
from quant.backtest.exits import ExitConfig

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
# Equivalence: default ExitConfig is a legacy no-op, even with OHLC present.
# ---------------------------------------------------------------------------


def test_default_exits_never_fire_a_bracket():
    """With OHLC columns present but ExitConfig at its default, no trade
    should ever exit via stop/target/trail/time/eod -- only signal or
    end-of-data, exactly like the pre-Phase-09 engine."""
    rows = _flat_candles(60)
    candles = _ohlc(rows)
    signals = _signals(60, buy_at=10, sell_at=40)
    result = run_backtest(candles, signals)
    assert result.trades["exit_reason"].to_list() == ["signal"]


def test_default_exits_config_is_disabled():
    assert ExitConfig().enabled is False


def test_open_position_still_force_closed_with_end_of_data_reason():
    rows = _flat_candles(30)
    candles = _ohlc(rows)
    signals = _signals(30, buy_at=10)  # never sells
    result = run_backtest(candles, signals)
    assert result.trades["exit_reason"].to_list() == ["end_of_data"]
    assert result.trades["closed_at_end"].to_list() == [1]


# ---------------------------------------------------------------------------
# Intrabar precedence
# ---------------------------------------------------------------------------


def test_stop_loss_fires_on_intrabar_low():
    rows = _flat_candles(20, price=100.0)
    # bar 11 is the entry fill bar (BUY at bar 10 close -> fill at bar 11 open).
    # Make bar 12 dip low enough to breach a 2-point stop without gapping.
    rows[12] = {**rows[12], "low": 97.0, "open": 100.0, "close": 99.5, "high": 100.2}
    candles = _ohlc(rows)
    signals = _signals(20, buy_at=10)
    cfg = BacktestConfig(exits=ExitConfig(stop_mode="points", stop_points=2.0))
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert trades[0]["exit_reason"] == "stop"
    entry_price = trades[0]["entry_price"]
    assert trades[0]["exit_price"] == pytest.approx(entry_price - 2.0)


def test_target_fires_on_intrabar_high():
    rows = _flat_candles(20, price=100.0)
    rows[12] = {**rows[12], "high": 104.0, "open": 100.0, "close": 101.0, "low": 99.8}
    candles = _ohlc(rows)
    signals = _signals(20, buy_at=10)
    cfg = BacktestConfig(
        exits=ExitConfig(
            stop_mode="points", stop_points=10.0, target_mode="points", target_points=2.0
        )
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert trades[0]["exit_reason"] == "target"
    entry_price = trades[0]["entry_price"]
    assert trades[0]["exit_price"] == pytest.approx(entry_price + 2.0)


def test_stop_wins_when_both_stop_and_target_breached_same_bar():
    rows = _flat_candles(20, price=100.0)
    # bar 12: both the 2-point stop AND the 2-point target are inside this bar.
    rows[12] = {**rows[12], "high": 104.0, "low": 96.0, "open": 100.0, "close": 100.0}
    candles = _ohlc(rows)
    signals = _signals(20, buy_at=10)
    cfg = BacktestConfig(
        exits=ExitConfig(
            stop_mode="points", stop_points=2.0, target_mode="points", target_points=2.0
        )
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert trades[0]["exit_reason"] == "stop"


def test_gap_through_stop_fills_at_open_not_at_stop_level():
    rows = _flat_candles(20, price=100.0)
    # bar 12 opens BELOW the 2-point stop entirely (a gap down).
    rows[12] = {**rows[12], "open": 90.0, "high": 90.5, "low": 89.0, "close": 89.5}
    candles = _ohlc(rows)
    signals = _signals(20, buy_at=10)
    cfg = BacktestConfig(exits=ExitConfig(stop_mode="points", stop_points=2.0))
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert trades[0]["exit_reason"] == "stop"
    # Fills at the bar's open (90.0), NOT at entry_price - 2.0 -- the gap
    # is what makes this honest.
    assert trades[0]["exit_price"] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# Trailing stop: only bars <= i-1 may move the trail.
# ---------------------------------------------------------------------------


def test_trailing_stop_ignores_the_current_bars_own_extreme():
    """A bar that makes a new high must not be able to move the trail
    based on ITS OWN extreme and then close itself against that same-bar
    level -- the trail level applicable to bar i can only reflect bars
    <= i-1. It is legitimate (and expected) for that extreme to move the
    trail as of the *next* bar, once it is `i-1`; this test asserts the
    one-bar causal delay, not that the trail never fires.
    """
    rows = _flat_candles(30, price=100.0)
    # Bar 15 makes a big new high; its own low/open/close stay normal, so
    # nothing about bar 15 itself should trigger an exit. If the trail
    # illegally used bar 15's own high to size bar 15's own stop level,
    # the tightened level would sit above bar 15's own (normal) low and
    # exit bar 15 itself. Correctly, only bar 16 -- once bar 15 is `i-1`
    # -- may react to that high.
    rows[15] = {**rows[15], "high": 130.0}
    candles = _ohlc(rows)
    signals = _signals(30, buy_at=10)
    cfg = BacktestConfig(
        exits=ExitConfig(trail_mode="atr", trail_atr_mult=3.0, atr_period=5)
    )
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    # Must NOT close on bar 15 itself...
    assert trades[0]["exit_time"] != rows[15]["timestamp"]
    # ...but MUST close on bar 16, once bar 15 is legitimately "i-1".
    assert trades[0]["exit_time"] == rows[16]["timestamp"]
    assert trades[0]["exit_reason"] == "stop"


# ---------------------------------------------------------------------------
# EOD square-off is wall-clock based, independent of bars-per-day.
# ---------------------------------------------------------------------------


def test_eod_squareoff_fires_by_wallclock_time_on_a_long_session_day():
    """August-shaped day: candles run to 15:39 (385 bars), unlike July's
    375-bar/15:29 day. EOD must still square off at the configured
    wall-clock cutoff, not at a fixed bar-index offset."""
    day_start = datetime(2026, 8, 3, 9, 15)
    n = 385  # 09:15 .. 15:39 inclusive, one bar per minute
    rows = _flat_candles(n, price=100.0, start=day_start)
    candles = _ohlc(rows)
    signals = _signals(n, buy_at=5, start=day_start)
    cfg = BacktestConfig(exits=ExitConfig(eod_squareoff="15:20"))
    result = run_backtest(candles, signals, cfg)
    trades = result.trades.to_dicts()
    assert trades[0]["exit_reason"] == "eod"
    assert trades[0]["exit_time"].time() == datetime(2026, 8, 3, 15, 20).time()


def test_entry_window_blocks_entries_outside_session():
    n = 60
    rows = _flat_candles(n, price=100.0)
    candles = _ohlc(rows)
    # BUY signal fires at a bar whose fill time is before 09:30.
    signals = _signals(n, buy_at=5)  # fill at bar 6 -> 09:21, before 09:30
    cfg = BacktestConfig(exits=ExitConfig(session_start="09:30"))
    result = run_backtest(candles, signals, cfg)
    assert result.trades.height == 0


# ---------------------------------------------------------------------------
# Schema stability
# ---------------------------------------------------------------------------


def test_trade_columns_appended_not_inserted():
    """Positional indices used by tests/test_phase05_backtest.py must be
    unchanged: entry_time at 1, entry_price at 4."""
    rows = _flat_candles(30)
    candles = _ohlc(rows)
    signals = _signals(30, buy_at=10, sell_at=20)
    result = run_backtest(candles, signals)
    cols = result.trades.columns
    assert cols[1] == "entry_time"
    assert cols[4] == "entry_price"
    assert cols[11] == "closed_at_end"
    for new_col in ("exit_reason", "mae", "mfe", "bars_held", "r_multiple"):
        assert new_col in cols
        assert cols.index(new_col) > 11


def test_bracket_exits_require_high_low_columns():
    n = 10
    candles = pl.DataFrame(
        {
            "timestamp": [BASE + timedelta(minutes=i) for i in range(n)],
            "open": [100.0] * n,
            "close": [100.0] * n,
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    signals = _signals(n, buy_at=2)
    cfg = BacktestConfig(exits=ExitConfig(stop_mode="points", stop_points=1.0))
    with pytest.raises(ValueError, match="high.*low|low.*high"):
        run_backtest(candles, signals, cfg)
