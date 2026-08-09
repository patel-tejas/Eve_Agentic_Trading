# Phase 14 — Human-Approved Live Trading

## Goal

Enable live order execution through DhanHQ with mandatory human approval at every step.

## What We're Building

The final phase: actual order execution on the broker. This requires extensive paper testing, risk validation, and human oversight.

## Deliverables

- DhanHQ order execution API integration
- Human approval gate (manual confirmation)
- Risk engine validation before every order
- Order status tracking
- Position reconciliation with broker
- Live P&L tracking

## Key Concepts

### Execution Pipeline

```
Signal
  ↓
Risk Engine (Phase 13)
  ↓
Human Approval Gate
  ↓
Order Validation
  ↓
DhanHQ Order API
  ↓
Fill Confirmation
  ↓
Position Update
  ↓
Reconciliation
```

### DhanHQ Order API

**Place Order:**
```python
# POST /v2/orders
{
    "security_id": "...",
    "exchange_segment": "NSE_FNO",
    "transaction_type": "BUY",  # or "SELL"
    "order_type": "MARKET",
    "product": "INTRADAY",
    "quantity": 50,  # 1 lot NIFTY
    "price": 0,      # market order
}
```

**Order Types:**
- MARKET: Execute at current market price
- LIMIT: Execute at specified price
- SL: Stop-loss order
- SL-M: Stop-loss market

### Human Approval Gate

```
Signal + Risk Check pass
     ↓
Notification to user:
  "BUY NIFTY FUT @ 24500.50"
  "Quantity: 50 (1 lot)"
  "Risk check: PASS"
     ↓
User approves/rejects
     ↓
If approved: place order
If rejected: skip trade
```

### Order Status Tracking

```
PLACED → PENDING → FILLED
                   → PARTIALLY FILLED
                   → CANCELLED
                   → REJECTED
```

### Position Reconciliation

```
Every 5 minutes:
1. Fetch positions from DhanHQ
2. Compare with internal portfolio
3. Detect discrepancies
4. Alert on mismatch
5. Auto-correct if safe
```

### Pre-Live Checklist

Before enabling live trading:
- [ ] Paper trading profitable for 30+ days
- [ ] Risk engine tested with extreme scenarios
- [ ] Kill switch tested
- [ ] Reconciliation tested
- [ ] All systems monitored
- [ ] Human approval workflow tested
- [ ] Emergency contacts configured

## Data Contracts

### Input
- Strategy signals
- Risk-checked orders
- Human approval

### Output
- DhanHQ orders
- Fill confirmations
- Position updates
- Reconciliation reports

## Dependencies

- Phase 13 (risk engine)
- Phase 12 (paper trading validated)
- DhanHQ trading account

## Definition of Done

- [ ] Order placement via DhanHQ API working
- [ ] Human approval gate working
- [ ] Risk engine validates every order
- [ ] Position reconciliation with broker
- [ ] Order status tracking
- [ ] Live P&L tracking
- [ ] Kill switch tested in live environment

## Open Questions

- Order type: market vs limit?
- Position sizing for live trades?
- How to handle partial fills?
- Reconciliation frequency?
- What constitutes "profitable enough" for paper → live transition?
