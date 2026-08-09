"""Backtest event engine.

Phase 05: position state machine (LONG/SHORT/FLAT), signal-at-close ->
execute-at-next-open (no look-ahead), per-trade log and bar-level
mark-to-market equity curve.

Execution rules
- Signals are decided at their bar's close; orders fill at the *next*
  bar's open plus configured slippage.
- FLAT -> BUY is a LONG entry, FLAT -> SELL is a SHORT entry.
- LONG exits on SELL (-> FLAT), SHORT exits on BUY (-> FLAT). Same
  direction signals while open are ignored.
- A position still open at series end is closed at the last close and
  flagged with ``closed_at_end=1``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import polars as pl

from quant.backtest.costs import CostConfig, round_trip_costs
from quant.backtest.execution import ExecutionConfig, adjusted_price
from quant.backtest.metrics import compute_metrics

Position = Literal["FLAT", "LONG", "SHORT"]


@dataclass(frozen=True)
class BacktestConfig:
    """Full backtest configuration for one run."""

    initial_capital: float = 1_000_000.0
    position_size: int = 1  # lots
    lot_size: int = 50  # NIFTY futures
    costs: CostConfig = field(default_factory=CostConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    @property
    def quantity(self) -> int:
        return self.position_size * self.lot_size


@dataclass(frozen=True)
class BacktestResult:
    """Output of one backtest run: trades, equity curve, metrics."""

    trades: pl.DataFrame
    equity: pl.DataFrame
    metrics: dict[str, float | int | str]


TRADE_COLUMNS = [
    "trade_id",
    "entry_time",
    "exit_time",
    "direction",
    "entry_price",
    "exit_price",
    "quantity",
    "gross_pnl",
    "costs",
    "net_pnl",
    "holding_periods",
    "closed_at_end",
]

EQUITY_COLUMNS = ["timestamp", "equity", "unrealized", "realized"]


def run_backtest(
    candles: pl.DataFrame,
    signals: pl.DataFrame,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Simulate ``signals`` against ``candles``; return trades + equity + metrics."""
    cfg = config or BacktestConfig()
    candles = candles.sort("timestamp")
    signals = signals.sort("timestamp").select(
        pl.col("timestamp"), pl.col("signal_type").alias("next_signal")
    )
    merged = candles.select("timestamp", "open", "close").join(signals, on="timestamp", how="inner")
    if merged.height == 0:
        raise ValueError("no overlapping bars between candles and signals")

    times = merged["timestamp"].to_list()
    opens = merged["open"].to_list()
    closes = merged["close"].to_list()
    next_signal = merged["next_signal"].to_list()
    n = merged.height

    quantity = cfg.quantity
    slippage = cfg.execution.slippage
    tick = slippage.tick_size
    capital = cfg.initial_capital

    trades: list[dict[str, object]] = []
    equity_rows: list[dict[str, object]] = []

    position: Position = "FLAT"
    trade_id = 0
    entry_time: datetime | None = None
    entry_price = 0.0
    entry_idx = 0
    realized = 0.0  # cumulative realized net P&L

    def open_trade(direction_labels: str, price: float, i: int) -> None:
        nonlocal position, entry_time, entry_price, entry_idx
        position = "LONG" if direction_labels == "LONG" else "SHORT"
        entry_time = times[i]
        entry_price = price
        entry_idx = i

    def close_trade(direction: str, exit_price: float, i: int, closed_at_end: bool) -> None:
        nonlocal realized, trade_id, position, entry_time, entry_price, entry_idx
        sign = 1.0 if direction == "LONG" else -1.0
        gross = (exit_price - entry_price) * quantity * sign
        costs = round_trip_costs(entry_price, exit_price, quantity, direction, cfg.costs)
        net = gross - costs
        realized += net
        trade_id += 1
        trades.append(
            {
                "trade_id": trade_id,
                "entry_time": entry_time,
                "exit_time": times[i],
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": quantity,
                "gross_pnl": gross,
                "costs": costs,
                "net_pnl": net,
                "holding_periods": i - entry_idx,
                "closed_at_end": int(closed_at_end),
            }
        )
        position = "FLAT"
        entry_time = None

    for i in range(n):
        pending = next_signal[i - 1] if i > 0 else None

        if position == "LONG" and pending == "SELL":
            exit_px = adjusted_price(opens[i], "sell", slippage, tick)
            close_trade("LONG", exit_px, i, closed_at_end=False)
        elif position == "SHORT" and pending == "BUY":
            exit_px = adjusted_price(opens[i], "buy", slippage, tick)
            close_trade("SHORT", exit_px, i, closed_at_end=False)
        elif position == "FLAT":
            if pending == "BUY":
                open_trade("LONG", adjusted_price(opens[i], "buy", slippage, tick), i)
            elif pending == "SELL":
                open_trade("SHORT", adjusted_price(opens[i], "sell", slippage, tick), i)

        # Mark to market at this bar's close
        unrealized = 0.0
        if position == "LONG":
            unrealized = (closes[i] - entry_price) * quantity
        elif position == "SHORT":
            unrealized = (entry_price - closes[i]) * quantity
        equity_rows.append(
            {
                "timestamp": times[i],
                "equity": capital + realized + unrealized,
                "unrealized": unrealized,
                "realized": realized,
            }
        )

    # Force-close any position open at the end of the series
    if position != "FLAT":
        side = "sell" if position == "LONG" else "buy"
        exit_px = adjusted_price(closes[-1], side, slippage, tick)
        close_trade(position, exit_px, n - 1, closed_at_end=True)

    trades_df = pl.DataFrame(
        trades,
        schema={
            "trade_id": pl.Int64,
            "entry_time": pl.Datetime("ms"),
            "exit_time": pl.Datetime("ms"),
            "direction": pl.Utf8,
            "entry_price": pl.Float64,
            "exit_price": pl.Float64,
            "quantity": pl.Int64,
            "gross_pnl": pl.Float64,
            "costs": pl.Float64,
            "net_pnl": pl.Float64,
            "holding_periods": pl.Int64,
            "closed_at_end": pl.Int64,
        },
        orient="row",
    )
    equity_df = pl.DataFrame(equity_rows, schema=EQUITY_COLUMNS, orient="row")
    metrics = compute_metrics(trades=trades_df, equity=equity_df, capital=capital)
    return BacktestResult(trades=trades_df, equity=equity_df, metrics=metrics)
