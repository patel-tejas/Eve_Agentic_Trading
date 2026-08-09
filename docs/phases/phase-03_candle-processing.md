# Phase 03 — Candle Processing

## Goal

Build 5-minute and 15-minute candles from the validated 1-minute source data, and verify correctness against provider data where possible.

## What We're Building

A candle aggregation pipeline that transforms 1-minute candles into higher timeframes. The 1-minute data is the canonical source; 5m and 15m are derived.

## Deliverables

- 5-minute candle dataset from 1-minute source
- 15-minute candle dataset from 1-minute source
- Boundary verification (candle alignment)
- Parquet files for each timeframe

## Key Concepts

### Candle Aggregation Rules

#### 5-Minute Candles
```
Group 1-minute candles in blocks of 5:
[09:15, 09:16, 09:17, 09:18, 09:19] → 09:15 candle

open  = first candle's open
high  = max of all 5 highs
low   = min of all 5 lows
close = last candle's close
volume = sum of all 5 volumes
OI    = last candle's OI
```

#### 15-Minute Candles
```
Group 1-minute candles in blocks of 15:
[09:15 ... 09:29] → 09:15 candle
[09:30 ... 09:44] → 09:30 candle
[09:45 ... 09:59] → 09:45 candle
...

Same aggregation rules as 5m.
```

### Candle Boundary Alignment

```
1m:  09:15 09:16 09:17 09:18 09:19 09:20 09:21 09:22 09:23 09:24 09:25 ...
5m:  09:15 ─────────────────────── 09:20 ─────────────────────── 09:25 ...
15m: 09:15 ──────────────────────────────────────────────────────────────── 09:30 ...
```

Boundaries:
- 5m boundaries: XX:00, XX:05, XX:10, XX:15, XX:20, XX:25, XX:30, XX:35, XX:40, XX:45, XX:50, XX:55
- 15m boundaries: XX:00, XX:15, XX:30, XX:45

### Polars Implementation

```python
import polars as pl

def aggregate_candles(df: pl.DataFrame, factor: int) -> pl.DataFrame:
    """
    Aggregate 1m candles into higher timeframe.
    factor: 5 for 5m, 15 for 15m
    """
    # Add group identifier
    df = df.with_columns(
        (pl.col("timestamp").dt.epoch("s") // (factor * 60)).alias("group_id")
    )
    
    # Aggregate per group
    result = df.group_by("group_id").agg([
        pl.col("timestamp").first().alias("timestamp"),
        pl.col("open").first(),
        pl.col("high").max(),
        pl.col("low").min(),
        pl.col("close").last(),
        pl.col("volume").sum(),
        pl.col("open_interest").last(),
    ])
    
    return result.sort("timestamp")
```

### Verification

```
- 5m candle count ≈ 1m count / 5
- 15m candle count ≈ 1m count / 15
- No data loss during aggregation
- OHLC integrity maintained
- Volume sums match
- First/last candles align correctly
```

## Data Contracts

### Input
- `data/raw/futures/NIFTY/2026-07/candles_1m.parquet`

### Output
- `data/processed/candles_5m.parquet`
- `data/processed/candles_15m.parquet`

### Schema (same for all timeframes)

| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime64[ns] | Candle open time |
| open | f64 | Open price |
| high | f64 | High price |
| low | f64 | Low price |
| close | f64 | Close price |
| volume | i64 | Volume |
| open_interest | i64 | Open interest |

## Dependencies

- Phase 02 (validated 1m data)

## Definition of Done

- [ ] 5m candles correctly aggregated from 1m
- [ ] 15m candles correctly aggregated from 1m
- [ ] Candle count ratio approximately correct
- [ ] OHLC integrity maintained
- [ ] Volume sums match source
- [ ] Boundary alignment verified
- [ ] Parquet files saved

## Open Questions

- How to handle partial candles at market open/close?
- Should derived timeframes include metadata (source timeframe, factor)?
- Cross-validation against Dhan's native 5m/15m data?
