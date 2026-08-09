"""Phase 05 unit tests: backtest engine, execution, costs, metrics.

Polars only; no network. Checks next-open execution (no look-ahead),
position state machine, cost math, slippage, metrics, determinism.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import polars as pl
import pytest

from quant.backtest.costs import (
    CostConfig,
    SlippageConfig,
    cost_of_order,
    round_trip_costs,
    slippage_ticks,
)
from quant.backtest.engine import run_backtest
from quant.backtest.execution import adjusted_price
from quant.backtest.metrics import compute_metrics

BASE = datetime(2026, 7, 1, 9, 15)


def _candles(n: int = 100) -> pl.DataFrame:
    rows = []
    for i in range(n):
        ts = BASE + timedelta(minutes=i)
        price = 100.0 + i * 0.5
        rows.append(
            {
                "timestamp": ts,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price + 0.25,
            }
        )
    return pl.DataFrame(rows, schema_overrides={"timestamp": pl.Datetime("ms")})


def _signals(buy_at: int, sell_at: int | None = None) -> pl.DataFrame:
    n = 100
    types = ["HOLD"] * n
    types[buy_at] = "BUY"
    if sell_at is not None:
        types[sell_at] = "SELL"
    return pl.DataFrame(
        {
            "timestamp": [BASE + timedelta(minutes=i) for i in range(n)],
            "signal_type": types,
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )


def test_entry_executes_at_next_candle_open():
    candles = _candles()
    signals = _signals(buy_at=10, sell_at=50)  # BUY at close of bar 10
    result = run_backtest(candles, signals)
    trades = result.trades
    assert len(trades) == 1
    row = trades.row(0)
    entry_time = row[1]
    assert entry_time == candles["timestamp"][11]  # bar 11 open fill
    entry_price = row[4]
    assert entry_price == candles["open"][11]


def test_long_exit_flat_then_short_entry():
    candles = _candles(120)
    types = ["HOLD"] * 120
    types[10] = "BUY"
    types[40] = "SELL"
    types[41] = "SELL"
    signals = pl.DataFrame(
        {
            "timestamp": [BASE + timedelta(minutes=i) for i in range(120)],
            "signal_type": types,
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    result = run_backtest(candles, signals)
    dirs = result.trades["direction"].to_list()
    assert dirs == ["LONG", "SHORT"]  # 41 closes LONG; 51 opens SHORT
    assert len(result.trades) == 2


def test_same_direction_signal_ignored_while_open():
    candles = _candles()
    signals = _signals(buy_at=10, sell_at=20)
    # make two BUYs back to back
    types = signals["signal_type"].to_list()
    types[11] = "BUY"
    signals = signals.with_columns(pl.Series("signal_type", types))
    result = run_backtest(candles, signals)
    assert len(result.trades) == 1  # second BUY ignored (already LONG)


def test_open_position_closed_at_end_flagged():
    candles = _candles(60)
    signals = _signals(10)  # never sells -> force close at end
    result = run_backtest(candles, signals)
    assert len(result.trades) == 1
    assert result.trades["closed_at_end"].to_list() == [1]
    assert result.trades["exit_time"][0] == candles["timestamp"][-1]
    assert result.trades["exit_price"][0] == candles["close"][-1]


def test_gross_pnl_matches_hand_calc():
    candles = _candles(60)
    signals = _signals(10, 40)
    result = run_backtest(candles, signals)
    t = result.trades.to_dicts()[0]
    entry_px = candles["open"][11]
    exit_px = candles["open"][41]
    qty = 50
    expected_gross = (exit_px - entry_px) * qty
    assert t["gross_pnl"] == pytest.approx(expected_gross)


def test_costs_math():
    cfg = CostConfig(brokerage_flat=20.0)
    buy = cost_of_order(24500.0, 50, "buy", cfg)
    sell = cost_of_order(24600.0, 50, "sell", cfg)
    # broker 20 + exchange 24500*50*0.00345% + sebi + stamp (buy) + gst 18%
    turnover_buy = 24500.0 * 50
    expect_buy = (
        20.0
        + turnover_buy * 0.0000345
        + turnover_buy * 0.000001
        + turnover_buy * 0.00003
        + (20.0 + turnover_buy * 0.0000345) * 0.18
    )
    assert buy == pytest.approx(expect_buy)
    # sell adds STT 0.0125% and no stamp
    turnover_sell = 24600.0 * 50
    expect_sell = (
        20.0
        + turnover_sell * 0.000125
        + turnover_sell * 0.0000345
        + turnover_sell * 0.000001
        + (20.0 + turnover_sell * 0.0000345) * 0.18
    )
    assert sell == pytest.approx(expect_sell)


def test_round_trip_direction_affects_stt():
    cfg = CostConfig()
    long_rt = round_trip_costs(24500.0, 24600.0, 50, "LONG", cfg)
    short_rt = round_trip_costs(24600.0, 24500.0, 50, "SHORT", cfg)
    # STT applies on the sell leg in both cases (LONG exit, SHORT entry)
    assert long_rt == pytest.approx(short_rt)


def test_slippage_adjusts_price_adversely():
    cfg = SlippageConfig(mode="ticks", entry_ticks=2, exit_ticks=1, tick_size=0.05)
    buy_px = adjusted_price(24500.0, "buy", cfg)
    sell_px = adjusted_price(24500.0, "sell", cfg)
    assert buy_px == pytest.approx(24500.0 + 2 * 0.05)
    assert sell_px == pytest.approx(24500.0 - 1 * 0.05)


def test_slippage_modes():
    assert slippage_ticks(SlippageConfig(mode="ideal"), "buy") == 0
    assert slippage_ticks(SlippageConfig(mode="normal"), "buy") == 1
    assert slippage_ticks(SlippageConfig(mode="stress"), "buy") == 3
    assert slippage_ticks(SlippageConfig(mode="stress", entry_ticks=5), "buy") == 5


def test_deterministic_output():
    candles = _candles(90)
    signals = _signals(10, 50)
    a = run_backtest(candles, signals)
    b = run_backtest(candles, signals)
    assert a.trades.equals(b.trades)
    assert a.equity.equals(b.equity)
    assert a.metrics == b.metrics


def test_equity_curve_length_and_mark():
    candles = _candles(50)
    signals = _signals(10, 40)
    result = run_backtest(candles, signals)
    eq = result.equity
    assert eq.height == 50
    t = result.trades.to_dicts()[0]
    # equity at the last bar: initial + realized net pnl
    assert eq["equity"][-1] == pytest.approx(1_000_000.0 + t["net_pnl"])
    # last bar has no open position (closed at 41)
    assert eq["unrealized"][-1] == 0.0


def test_metrics_basic():
    trades = pl.DataFrame(
        [
            {"net_pnl": 100.0, "gross_pnl": 120.0, "holding_periods": 3},
            {"net_pnl": -50.0, "gross_pnl": -30.0, "holding_periods": 2},
            {"net_pnl": 80.0, "gross_pnl": 95.0, "holding_periods": 4},
        ],
        schema={
            "net_pnl": pl.Float64,
            "gross_pnl": pl.Float64,
            "holding_periods": pl.Int64,
        },
    )
    equity = pl.DataFrame(
        {
            "timestamp": [BASE + timedelta(days=i) for i in range(5)],
            "equity": [1_000_000.0, 1_000_100.0, 1_000_050.0, 1_000_130.0, 1_000_200.0],
        },
        schema_overrides={"timestamp": pl.Datetime("ms")},
    )
    m = compute_metrics(trades=trades, equity=equity, capital=1_000_000.0)
    assert m["total_trades"] == 3
    assert m["win_rate"] == pytest.approx(2 / 3)
    assert m["gross_pnl"] == pytest.approx(120.0 - 30.0 + 95.0)
    assert m["profit_factor"] == pytest.approx((120.0 + 95.0) / 30.0)
    assert m["max_drawdown_pct"] == pytest.approx(50.0 / 1_000_100.0)
    assert m["longest_win_streak"] == 1
    assert m["longest_loss_streak"] == 1
    assert m["expectancy"] == pytest.approx((100.0 - 50.0 + 80.0) / 3)
    assert m["trading_days"] == 5
    assert m["sharpe"] > 0
    assert m["sortino"] >= 0
    days = 5
    ann_return = m["total_return_pct"] * 252 / days
    assert m["calmar"] == pytest.approx(ann_return / m["max_drawdown_pct"])
