# Phase 12 — Paper Trading

## Goal

Run the strategy in real-time with simulated execution: live signals, paper portfolio tracking, slippage simulation, and P&L monitoring.

## What We're Building

Paper trading proves the strategy works in real-time without risking real money. It must use the same strategy code as the backtester.

## Deliverables

- Live signal generation from real-time candles
- Simulated order execution
- Paper portfolio state management
- Slippage simulation
- Real-time P&L tracking
- Monitoring dashboard

## Key Concepts

### Paper Trading Architecture

```
Live Dhan Feed
      ↓
Strategy Engine (same as backtester)
      ↓
Risk Engine (Phase 13)
      ↓
Simulated Execution
      ↓
Paper Portfolio
```

### Paper Portfolio

```python
@dataclass
class PaperPosition:
    instrument: str
    direction: str       # "LONG" or "SHORT"
    entry_price: float
    entry_time: datetime
    quantity: int
    current_price: float
    unrealized_pnl: float

@dataclass
class PaperPortfolio:
    positions: list[PaperPosition]
    cash: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
```

### Execution Simulation

```
Signal received
     ↓
Apply slippage (configurable)
     ↓
Simulate fill at signal price ± slippage
     ↓
Update portfolio
     ↓
Record trade
```

### Tracking

```
- Signal timestamp
- Expected entry price
- Simulated fill price
- Slippage applied
- Exit price
- P&L per trade
- Latency (signal → execution)
```

### Monitoring

```
- Open positions
- Current P&L
- Today's trades
- Win/loss streak
- Drawdown
- Strategy health
```

## Data Contracts

### Input
- Live candle stream (Phase 10)
- Strategy engine (Phase 04)
- Risk engine (Phase 13)

### Output
- Paper portfolio state
- Trade log
- P&L report

## Dependencies

- Phase 10 (real-time data)
- Phase 04 (strategy engine)
- Phase 13 (risk engine)

## Definition of Done

- [ ] Live signals generated correctly
- [ ] Paper execution simulated
- [ ] Portfolio state tracked
- [ ] Slippage applied
- [ ] P&L calculated correctly
- [ ] Same strategy code as backtester
- [ ] Monitoring dashboard working

## Open Questions

- How to handle market hours (auto-square off)?
- Position sizing for paper trades?
- Should paper trades be stored in Snowflake?
- How long should paper trading run before live?
