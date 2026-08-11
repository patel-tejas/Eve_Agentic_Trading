---
description: Use when explaining backtest execution, slippage, costs, or interpreting P&L metrics and the decision rule.
---

# Futures Backtesting

## Execution model

Signal at bar close → fill at **next bar's open** + slippage. No intra-bar fill.
FLAT→BUY opens LONG, FLAT→SELL opens SHORT. Same-direction signals while open are ignored.
A position open at series end is closed at last close, flagged `closed_at_end=1`.

## Slippage modes

`ideal` (0 ticks) · `normal` (1 tick adverse, default for research) · `stress` (3+ ticks) · `ticks` (explicit). Tick = ₹0.05.

## Costs per round trip (NIFTY futures, 1 lot = 50 units)

Brokerage ₹20/leg + STT 0.0125% sell + exchange 0.00345% + SEBI 0.0001% + stamp 0.003% + GST 18%.
Rule of thumb: ~₹330+ per round trip.

## Key metrics

| Metric | Meaning |
|---|---|
| `net_pnl` | gross − costs; the primary number to report |
| `profit_factor` | gross winners ÷ abs(gross losers) |
| `max_drawdown_pct` | % peak-to-trough on equity curve |
| `sharpe` / `sortino` | annualized (252 days) from daily equity returns |

## Decision rule

net > 0 AND profit_factor > 1.25 AND max drawdown < 10% per timeframe.
Fewer than 20 trades per month = "directional, not statistically decisive" — always say so.