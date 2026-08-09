# Phase 10 — Real-Time Data

## Goal

Connect to DhanHQ WebSocket for live market data, build real-time candles, and feed the feature engine.

## What We're Building

The live data pipeline that replaces historical batch data with streaming market data. This is the bridge from research to real-time execution.

## Deliverables

- DhanHQ WebSocket connection
- Authentication and subscription management
- Reconnection handling
- Real-time candle builder (1m, 5m, 15m)
- Feature engine for live signals

## Key Concepts

### DhanHQ WebSocket

**Connection:** `wss://stream.dhan.co`

**Authentication:**
```json
{
    "type": "auth",
    "client-id": "<DHAN_CLIENT_ID>",
    "access-token": "<DHAN_ACCESS_TOKEN>"
}
```

**Subscription:**
```json
{
    "type": "subscribe",
    "instrument": "NSE_FNO",
    "security-id": "<contract_security_id>",
    "mode": "full"  // "full", "quote", "snap"
}
```

**Message format:**
```json
{
    "type": "tick",
    "security-id": "...",
    "last-price": 24500.50,
    "open": 24480.00,
    "high": 24510.00,
    "low": 24475.00,
    "close": 24500.50,
    "volume": 1500000,
    "open-interest": 12000000,
    "timestamp": "2026-07-01T09:15:00+05:30"
}
```

### Real-Time Candle Builder

```
Tick stream
     ↓
Buffer ticks by timestamp minute
     ↓
Aggregate into 1m candle
     ↓
On candle close: emit 1m candle
     ↓
Roll up into 5m, 15m candles
```

### Reconnection Strategy

```
Connection lost
     ↓
Wait 1 second
     ↓
Reconnect
     ↓
Re-authenticate
     ↓
Re-subscribe
     ↓
Resume from last received tick
```

### Feature Engine

Real-time feature computation on live candles:
```
Live candle → EMA 9 → EMA 15 → Angle → Signal
```

Same code as backtester, but on live data.

## Data Contracts

### Input
- DhanHQ WebSocket stream
- Contract security IDs

### Output
- Real-time candle buffer
- Live feature values
- Live signals

## Dependencies

- Phase 01 (instrument discovery)
- Phase 04 (strategy engine for live signals)
- DhanHQ WebSocket access

## Definition of Done

- [ ] WebSocket connection established
- [ ] Authentication working
- [ ] Subscription to NIFTY Futures working
- [ ] Reconnection handling tested
- [ ] Real-time 1m candle builder working
- [ ] 5m and 15m candles rolling up correctly
- [ ] Feature engine producing live signals

## Open Questions

- Maximum concurrent subscriptions?
- WebSocket message rate limits?
- How to handle network interruptions?
- Should we persist raw tick data?
- Latency requirements for live signals?
