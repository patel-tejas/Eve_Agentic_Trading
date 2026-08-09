# Phase 09 — Snowflake

## Goal

Set up Snowflake as the long-term historical data warehouse for research data, experiment results, and analytical queries.

## What We're Building

A cloud data warehouse that stores all research data durably, supports complex analytical queries, and enables historical research across months/years of data.

## Deliverables

- Snowflake warehouse provisioned
- Schema designed (RAW, MARKET, FEATURES, STRATEGY, EXECUTION)
- Data ingestion pipeline from Parquet to Snowflake
- Dataset versioning in Snowflake
- Experiment storage
- Analytical query templates

## Key Concepts

### Snowflake Schema Design

```
TRADING_PLATFORM
├── RAW
│   ├── FUTURES_CANDLES
│   ├── MARKET_TICKS
│   └── MARKET_DEPTH
├── MARKET
│   ├── CANDLES_1M
│   ├── CANDLES_5M
│   └── CANDLES_15M
├── FEATURES
│   ├── PRICE_FEATURES
│   ├── VOLUME_FEATURES
│   ├── FUTURES_FEATURES
│   └── ORDERBOOK_FEATURES
├── STRATEGY
│   ├── STRATEGY_CONFIGS
│   ├── SIGNALS
│   ├── BACKTESTS
│   └── PERFORMANCE
└── EXECUTION
    ├── ORDERS
    ├── FILLS
    └── POSITIONS
```

### Data Ingestion

```
Local Parquet
     ↓
PyArrow / Polars
     ↓
Snowflake connector
     ↓
Snowflake tables
```

### Dataset Versioning

```sql
-- Version tracking
CREATE TABLE dataset_versions (
    version_id INT AUTO_INCREMENT,
    dataset_name VARCHAR,
    version VARCHAR,      -- "nifty_futures_july_2026_v1"
    created_at TIMESTAMP,
    source_hash VARCHAR,
    row_count INT,
    metadata VARIANT
);
```

### Experiment Storage

```sql
CREATE TABLE experiments (
    experiment_id VARCHAR PRIMARY KEY,  -- "EXP-2026-0001"
    config VARIANT,                      -- strategy config JSON
    dataset_version VARCHAR,
    results VARIANT,                     -- metrics JSON
    created_at TIMESTAMP,
    engine_version VARCHAR
);
```

### Analytical Queries

**Example: Find similar volatility periods**
```sql
SELECT 
    date_trunc('week', timestamp) AS week,
    AVG(daily_range) AS avg_range,
    STDDEV(daily_range) AS vol_range
FROM market_features
WHERE instrument = 'NIFTY_FUT'
GROUP BY 1
ORDER BY 2 DESC;
```

**Example: Compare strategy across months**
```sql
SELECT 
    month,
    SUM(net_pnl) AS total_pnl,
    COUNT(*) AS trades,
    AVG(win_rate) AS avg_win_rate
FROM strategy_performance
WHERE strategy_name = 'ema_9_15_angle_30'
GROUP BY 1;
```

## Data Contracts

### Input
- Local Parquet files from `data/`
- Experiment results from Phase 08

### Output
- Snowflake tables with all research data
- Query templates for common analyses

## Dependencies

- Phase 08 (advanced research results to store)
- Snowflake account

## Definition of Done

- [ ] Snowflake warehouse provisioned
- [ ] Schema created
- [ ] Parquet → Snowflake ingestion working
- [ ] Dataset versioning working
- [ ] Experiment storage working
- [ ] Query templates documented
- [ ] Agent can query Snowflake (Phase 07 integration)

## Open Questions

- Snowflake sizing (XS for dev?)
- Cost management (auto-suspend, auto-resume)
- Should we use Snowpark for Python UDFs?
- Data retention policy?
