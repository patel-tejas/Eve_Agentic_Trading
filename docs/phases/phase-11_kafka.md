# Phase 11 — Kafka

## Goal

Introduce Apache Kafka as the event streaming layer for decoupled, scalable, replayable market data distribution.

## What We're Building

Kafka sits between data ingestion and consumers (strategy, storage, monitoring, analytics). It provides event replay, buffer management, and decoupled architecture.

## Deliverables

- Kafka cluster (local dev: docker-compose)
- Topic design for market events
- Producer: DhanHQ WebSocket → Kafka
- Consumer: Kafka → strategy engine
- Consumer: Kafka → storage
- Consumer: Kafka → monitoring
- Event replay capability

## Key Concepts

### Why Kafka

The initial Dhan → Python → Parquet pipeline is too small for Kafka. Kafka becomes useful for:
- Event replay (reprocess historical data)
- Decoupled consumers (strategy, storage, analytics)
- Buffer management (handle tick bursts)
- Multiple strategy consumers
- Scalable ingestion

### Topic Design

```
market.ticks.{instrument}     ← raw tick data
market.candles.{timeframe}    ← aggregated candles
market.signals.{strategy}    ← strategy signals
market.orders.{exchange}     ← order events
system.heartbeats            ← health checks
```

### Producer

```
DhanHQ WebSocket
     ↓
Tick normalizer
     ↓
Kafka producer
     ↓
market.ticks.NIFTY_FUT
```

### Consumers

```
market.ticks.NIFTY_FUT
     ├──> Candle builder → market.candles.{1m,5m,15m}
     ├──> Storage writer → Parquet / Snowflake
     └──> Monitoring → dashboard
```

### Event Schema (Avro/JSON)

```json
{
    "event_type": "tick",
    "instrument": "NIFTY_FUT",
    "security_id": "...",
    "timestamp": "2026-07-01T09:15:00.000+05:30",
    "data": {
        "open": 24500.00,
        "high": 24510.00,
        "low": 24490.00,
        "close": 24505.50,
        "volume": 50000,
        "oi": 12000000
    }
}
```

### Replay

Kafka retains events for configurable duration (e.g., 7 days). This allows:
- Reprocessing data after bug fixes
- Backtesting on live data
- Debugging strategy behavior

## Data Contracts

### Input
- DhanHQ WebSocket stream
- Existing consumers (strategy, storage)

### Output
- Kafka topics with market events
- Consumer offsets tracked

## Dependencies

- Phase 10 (real-time data source)
- Docker (for local Kafka)

## Definition of Done

- [ ] Kafka cluster running (docker-compose)
- [ ] Topics created with proper partitioning
- [ ] Producer: Dhan → Kafka working
- [ ] Consumer: Kafka → candle builder working
- [ ] Consumer: Kafka → storage working
- [ ] Event replay tested
- [ ] Multiple consumers working simultaneously

## Open Questions

- Local dev: docker-compose or KRaft mode?
- Topic partitioning strategy (by instrument? by time?)
- Schema registry (Avro vs JSON)?
- Retention policy (how many days?)
- Monitoring: Kafka UI or custom dashboard?
