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

- [ ] No look-ahead bias (entries at next candle open)
- [ ] Transaction costs applied correctly
- [ ] Slippage configurable
- [ ] All metrics implemented
- [ ] Results reproducible
- [ ] Trade log complete
- [ ] Equity curve generated

## Open Questions

- How to handle partial fills (not applicable for backtest)?
- Should we support intraday position squaring?
- Cost model: flat brokerage or percentage-based?
- How to handle market gaps (overnight, holidays)?
