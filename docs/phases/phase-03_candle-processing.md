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

- [x] 5m candles correctly aggregated from 1m
- [x] 15m candles correctly aggregated from 1m
- [x] Candle count ratio approximately correct
- [x] OHLC integrity maintained
- [x] Volume sums match source
- [x] Boundary alignment verified
- [x] Parquet files saved

### July 2026 Verification (2026-08-09)

NIFTY futures, 8625 validated 1m bars -> `data/processed/futures/NIFTY/2026-07/`:

| Timeframe | Bars | Checks | Volume 1m vs derived |
|-----------|------|--------|----------------------|
| 5m | 1725 | all pass | 25,324,715 == 25,324,715 |
| 15m | 575 | all pass | 25,324,715 == 25,324,715 |

Every bucket is full-sized (75/day for 5m, 25/day for 15m, no partial trailing
buckets), all bucket opens sit on wall-clock grids (09:15, 09:20, ... and
09:15, 09:30, ...), first/last candles align to the session edges, and OHLC of
derived candles holds. Reports live next to each dataset:
`{1m,5m,15m}/verification_report.json` plus `dataset_metadata.json`.

Implementation notes:

- Aggregation uses polars `group_by_dynamic` with `closed="left"`, `label="left"`.
- Verified a polars gotcha: `dt.hour()/dt.minute()` are Int8 and overflow during
  `hour * 60`; any minute-of-day arithmetic must cast to Int64 first.

## Open Questions (resolved)

- **Partial candles at open/close?** NSE F&O sessions are complete
  (09:15-15:29 = 375 1m bars), so every bucket is full. If a partial trailing
  bucket ever appears (truncated source), it is kept, not dropped, and
  `bucket_size` warns.
- **Derived timeframe metadata?** Yes: `dataset_metadata.json` per timeframe
  (source, timeframe_minutes, bars, indicator params) + `verification_report.json`.
- **Cross-validation against Dhan native 5m/15m?** Deferred: counts, volumes,
  and boundaries are verified against the canonical 1m source, which is the
  stronger invariant; Dhan-side cross-check can be added when a second data
  source is pulled.
