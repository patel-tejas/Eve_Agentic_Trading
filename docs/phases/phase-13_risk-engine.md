# Phase 13 — Risk Engine

## Goal

Build the production risk layer: position limits, daily loss limits, trade frequency limits, kill switch, and reconciliation.

## What We're Building

The risk engine sits between strategy signals and order execution. It prevents catastrophic losses and enforces trading rules.

## Deliverables

- Position limit checks
- Daily loss limit
- Trade frequency limits
- Consecutive loss tracking
- Emergency kill switch
- Duplicate order protection
- Position reconciliation
- Order status reconciliation

## Key Concepts

### Risk Check Pipeline

```
Signal
  ↓
Position check (max position size)
  ↓
Daily loss check (max daily loss)
  ↓
Trade frequency check (max trades/day)
  ↓
Consecutive loss check (max consecutive losses)
  ↓
Market hours check
  ↓
Duplicate order check
  ↓
Order validation
  ↓
Human approval (for live)
  ↓
Execution
```

### Risk Limits

```python
class RiskConfig:
    max_position_size: int = 5        # lots
    max_daily_loss: float = 50000.0   # ₹50,000
    max_trades_per_day: int = 20
    max_consecutive_losses: int = 5
    kill_switch_enabled: bool = True
    market_hours_only: bool = True
```

### Kill Switch

```
Emergency stop:
- Close all positions immediately
- Cancel all pending orders
- Disable new orders
- Alert user
```

### Position Reconciliation

```
Compare:
- Paper portfolio positions
- Broker-reported positions (when live)
- Detect discrepancies
- Alert on mismatch
```

### Duplicate Order Protection

```
Before placing order:
- Check if same signal already executed
- Check if order already pending
- Prevent duplicate entries
```

## Data Contracts

### Input
- Strategy signals
- Portfolio state
- Risk config

### Output
- Risk check result (approve/reject)
- Risk log
- Reconciliation report

## Dependencies

- Phase 12 (paper trading)
- Phase 04 (strategy engine)

## Definition of Done

- [ ] All risk checks implemented
- [ ] Kill switch working
- [ ] Position reconciliation working
- [ ] Duplicate order protection working
- [ ] Risk limits configurable
- [ ] Risk log complete

## Open Questions

- How to handle kill switch activation?
- Should risk limits be per-strategy or global?
- How to reconcile with broker when live?
- Alert mechanism (email, SMS, dashboard)?
