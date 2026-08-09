# Phase 05 — Backtester

## Goal

Build a reproducible backtest engine that simulates trading with realistic execution assumptions: next-candle entries, transaction costs, slippage, and comprehensive performance metrics.

## What We're Building

The backtesting engine takes signals from Phase 04 and simulates what would have happened if we traded them. It must be free of look-ahead bias and account for real-world frictions.

## Deliverables

- Event-driven backtest engine
- Position tracking (long/short/flat)
- Entry/exit execution at next candle open
- Transaction cost model (Indian futures)
- Configurable slippage model
- Comprehensive performance metrics
- Reproducible results

## Key Concepts

### Execution Model (No Look-Ahead)

```
Signal generated at candle t close
        ↓
Entry/exit at candle t+1 open
```

This prevents using future information.

### Position States

```
FLAT → BUY signal → LONG
LONG → SELL signal → FLAT
FLAT → SELL signal → SHORT
SHORT → BUY signal → FLAT
```

### Transaction Costs (Indian Futures)

```
Gross P&L
  - Brokerage (flat per trade or %)
  - Exchange charges (NSE)
  - GST (18% on brokerage + exchange charges)
  - SEBI charges
  - Stamp duty
  - STT (Securities Transaction Tax)
  - Slippage
= Net P&L
```

Typical Indian futures cost structure:
```
Brokerage:        ₹20 per order (flat) or 0.03%
STT:              0.0125% on sell side
Exchange txn:     0.00345%
SEBI fees:        0.0001%
Stamp duty:       0.003% (varies by state)
GST:              18% on (brokerage + exchange)
```

### Slippage Models

```python
class SlippageConfig:
    mode: str  # "ideal", "normal", "stress", "ticks"
    entry_ticks: int = 0     # ticks above/below signal price
    exit_ticks: int = 0
    tick_size: float = 0.05  # NIFTY: 0.05
```

### Performance Metrics

**Minimum set:**
```
- Total trades
- Winning trades / Losing trades
- Win rate
- Gross P&L
- Net P&L (after costs)
- Average trade P&L
- Average winner / Average loser
- Profit factor (gross wins / gross losses)
- Maximum drawdown
- Average holding time
- Longest winning/losing streak
- Sharpe ratio
- Sortino ratio
```

**Additional:**
```
- Calmar ratio
- Expectancy
- Daily P&L
- Monthly P&L
- Trade distribution histogram
- Drawdown duration
```

### Backtest Engine Architecture

```python
class BacktestEngine:
    def run(self, candles: DataFrame, signals: DataFrame, config: BacktestConfig) -> BacktestResult:
        """
        Event-driven loop:
        for each candle:
            check if we have an open position
            check if signal triggers entry/exit
            execute at next candle open
            track P&L
            record metrics
        """
```

### Backtest Configuration

```python
class BacktestConfig:
    strategy_config: StrategyConfig
    cost_model: str           # "india_futures_v1"
    slippage: SlippageConfig
    initial_capital: float
    position_size: int        # lots
    lot_size: int             # NIFTY: 50
```

## Data Contracts

### Input
- `data/results/signals_{1m,5m,15m}.parquet`
- Candle data
- `BacktestConfig`

### Output
- `data/results/trades_{1m,5m,15m}.parquet`
- `data/results/metrics_{1m,5m,15m}.json`
- `data/results/equity_curve_{1m,5m,15m}.parquet`

### Trade Schema

| Column | Type | Description |
|--------|------|-------------|
| trade_id | i64 | Unique trade ID |
| entry_time | datetime | Entry candle timestamp |
| exit_time | datetime | Exit candle timestamp |
| direction | utf8 | "LONG" or "SHORT" |
| entry_price | f64 | Entry price (next candle open) |
| exit_price | f64 | Exit price (next candle open) |
| quantity | i64 | Number of units |
| gross_pnl | f64 | Before costs |
| costs | f64 | Total transaction costs |
| net_pnl | f64 | After costs |
| holding_periods | i64 | Number of candles held |

## Dependencies

- Phase 04 (signal engine)
- Phase 03 (candle data)

## Definition of Done

- [x] No look-ahead bias (entries at next candle open)
- [x] Transaction costs applied correctly
- [x] Slippage configurable
- [x] All metrics implemented
- [x] Results reproducible
- [x] Trade log complete
- [x] Equity curve generated

### July 2026 Baseline (2026-08-09)

`data/results/futures/NIFTY/2026-07/{trades,metrics,equity}_{1m,5m,15m}.*`
Baseline config: 1 lot x 50, capital 10L, ideal slippage (0 ticks),
brokerage 20/order, STT 0.0125% (sell), exchange 0.00345%, SEBI 0.0001%,
stamp 0.003% (buy), GST 18%.

| Timeframe | Trades | Net P&L | Win rate | Profit factor | Max DD (equity) |
|-----------|--------|---------|----------|---------------|-----------------|
| 1m | 2 | -18,662 | 0% | 0.00 | 4.0% |
| 5m | 4 | -20,205 | 25% | 0.10 | 4.0% |
| 15m | 4 | +5,757 | 25% | 1.35 | 2.6% |

Observations:

- Only 15m is net positive in July; 1m/5m lose after costs. Baseline config
  is deliberately untuned (calibration -> phase 08 research).
- Round-trip costs ~ 335 INR/52 lot-turnover (~0.05% of turnover): brokerage
  40 + STT + exchange + SEBI + stamp + GST.
- Trade 4 (15m LONG, 24 Jul) carried +27,250 gross and was force-closed at
  the end of the sample (closed_at_end=1).
- Equity curve is mark-to-market at each bar close; final equity =
  initial_capital + sum(net P&L).

Implementation notes:

- Engine is an explicit bar loop over (candle x signal) inner joins;
  signals are consumed at close(t) and filled at open(t+1) with slippage.
- Position state machine: FLAT -> BUY: LONG, FLAT -> SELL: SHORT,
  LONG -> SELL: FLAT, SHORT -> BUY: FLAT; same-direction signals ignored.
- Trades schema matches the phase spec + `closed_at_end` marker.

## Open Questions (resolved)

- **Partial fills?** Not modeled: backtest assumes every order fills at the
  execution price (position_size is 1 lot for now).
- **Intraday squaring?** Not implemented; positions may be carried
  overnight/holdings beyond the session. Add an intraday-exit config in a
  later phase if the strategy requires it.
- **Flat or % brokerage?** Flat per order (20 INR) with a `brokerage_flat`
  knob; percentage mode can be added.
- **Market gaps (overnight/holidays)?** Execution uses the first available
  next bar's open; a missing bar means the order fills at the next traded
  bar's open. Holding-period counts bars of the working timeline.
