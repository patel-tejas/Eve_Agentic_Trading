# Phase 02 — Data Validation

## Goal

Validate the downloaded 1-minute candle dataset for completeness, correctness, and consistency before any downstream processing.

## What We're Building

A validation layer that catches data quality issues early: missing candles, duplicate timestamps, OHLC integrity violations, volume anomalies, and contract metadata mismatches. Bad data in = bad backtests out.

## Deliverables

- Validation script that runs against `candles_1m.parquet`
- Report of all validation checks (pass/fail)
- Cleaned dataset (if minor issues found) or clear error report (if major issues found)
- Validation metadata saved for audit trail

## Key Concepts

### Validation Checks

#### 1. Timestamp Validation
```
- All timestamps within July 2026
- Timestamps in IST (UTC+5:30)
- No future timestamps
- Monotonically increasing
- No duplicates
```

#### 2. Trading Hours
```
- NSE F&O: 09:15 - 15:30 IST
- No candles outside market hours
- Correct number of candles per day (~375 for 1m)
- Lunch break handling (if applicable)
```

#### 3. OHLC Integrity
```
- high >= open, close, low
- low <= open, close, high
- open and close within [low, high]
- No negative prices
- No zero prices
- No NaN values
```

#### 4. Volume Validation
```
- volume >= 0
- Detect zero-volume candles (may indicate data issues)
- Flag unusually low/high volume days
```

#### 5. Open Interest Validation
```
- OI >= 0
- OI changes are plausible (no massive jumps)
- OI present for futures contracts
```

#### 6. Continuity Checks
```
- No gaps during trading hours
- First candle of day starts near previous day's close
- No missing days (excluding holidays)
```

### Validation Report Format

```json
{
  "dataset": "NIFTY_FUT_2026-07_1m",
  "total_candles": 9000,
  "checks": [
    {"name": "timestamp_monotonic", "status": "pass"},
    {"name": "no_duplicates", "status": "pass"},
    {"name": "ohlc_integrity", "status": "pass", "failures": 0},
    {"name": "market_hours", "status": "pass"},
    {"name": "missing_candles", "status": "warn", "details": "3 gaps detected"},
    {"name": "volume_anomalies", "status": "pass"}
  ],
  "overall": "pass_with_warnings"
}
```

### Data Quality Metrics

```python
@dataclass
class ValidationReport:
    dataset: str
    total_candles: int
    date_range: tuple[datetime, datetime]
    trading_days: int
    checks: list[CheckResult]
    overall_status: str  # "pass", "pass_with_warnings", "fail"
    warnings: list[str]
    errors: list[str]
```

## Tech References

| Library | Usage |
|---------|-------|
| `polars` | DataFrame operations for validation |
| `duckdb` | SQL queries for complex checks |
| `pydantic` | Schema validation models |

## Data Contracts

### Input
- `data/raw/futures/NIFTY/2026-07/candles_1m.parquet`
- `data/raw/futures/NIFTY/2026-07/contract_metadata.json`

### Output
- `data/raw/futures/NIFTY/2026-07/validation_report.json`
- Optionally: `data/raw/futures/NIFTY/2026-07/candles_1m_clean.parquet`

## Dependencies

- Phase 01 (data acquisition)

## Definition of Done

- [x] All 6 validation checks implemented
- [x] Validation report generated for July 2026 dataset
- [x] No critical errors in dataset
- [x] Warnings documented and explained
- [x] Validation is reproducible (same input = same report)
- [x] Validation metadata tied to dataset version

### July 2026 Baseline (2026-08-09)

- Status: `pass_with_warnings`, 0 errors
- `volume_sanity` warn: 388 zero-volume 1m bars (4.5%) — scattered single-minute
  gaps with no trades, not a contiguous feed outage; price/OHLC unaffected.
  Zero-volume bars are retained for aggregation. No auto-fix needed.
- All other checks pass (`timestamp_monotonic`, `no_duplicates`, `market_hours`,
  `daily_bar_counts`, `ohlc_integrity`, `open_interest_sanity`, `continuity`).

## Open Questions

- How to handle market holidays (July 2026: any holidays?)
- What threshold for "unusual volume"?
- Should validation auto-fix minor issues or flag for manual review?
- Do we need cross-validation against NSE official data?
