# Futures Backtesting (Phase 05)

## Execution model

- Signals are decided at their bar's **close**; orders fill at the **next
  bar's open** plus adverse slippage. There is no intra-bar fill, ever.
- FLAT→BUY opens LONG, FLAT→SELL opens SHORT. Same-direction signals while
  open are ignored.
- A position still open at series end is closed at the last close and
  flagged `closed_at_end=1` (its P&L is included).

## Slippage

`SlippageConfig.mode`: `ideal` (0 ticks), `normal` (1 tick adverse —
the default for research), `stress` (≥3 ticks), `ticks` (explicit
entry/exit ticks). Tick = 0.05 (NIFTY futures).

## Costs (per round trip, NIFTY futures, 1 lot = 50)

- Brokerage: flat ₹20 per order leg
- STT: 0.0125% on the sell leg only
- Exchange charge: 0.00345% both legs
- SEBI: 0.0001%, Stamp duty: 0.003% (buy), GST 18% on (brokerage + exchange)

Rule of thumb: ~₹330+ per round trip, so ₹10k+ net P&L with < 10 trades is
not noise.

## Metrics glossary

| Metric | Meaning |
|---|---|
| `net_pnl` | gross − costs; the number to quote |
| `profit_factor` | gross P&L of winners ÷ \|gross P&L\| of losers |
| `max_drawdown_pct` | % peak-to-trough on the equity curve |
| `sharpe`/`sortino` | annualized (252) from daily equity returns |
| `calmar` | annualized return ÷ max drawdown |
| `trading_days` | unique days in the equity curve |

## Interpretation rules

- Costs and slippage are already inside every metric — never add them on.
- Decision rule used in this project: net > 0 AND PF > 1.25 AND max
  drawdown < 10% (per timeframe).
- Fewer than ~20 trades per month means "directional, not statistically
  decisive". Say so.
- 1m is the most active timeframe and the most cost-sensitive.