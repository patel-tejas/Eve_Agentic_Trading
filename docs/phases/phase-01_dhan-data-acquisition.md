# Phase 01 — DhanHQ Data Acquisition

## Goal

Authenticate with DhanHQ, discover NIFTY Futures contracts, download July 2026 1-minute historical candles, normalize the data, and save as Parquet.

## What We're Building

The data ingestion pipeline — the foundation of all downstream research. This phase connects to DhanHQ's REST API, resolves the correct futures contract, fetches historical candle data, and stores it in a canonical format.

## Deliverables

- DhanHQ authentication working (client ID + access token)
- NIFTY Futures instrument discovered from instrument master
- July 2026 contract(s) identified and metadata stored
- 1-minute candle data downloaded and saved as Parquet
- Data normalized to internal Candle schema
- Contract metadata JSON saved alongside Parquet

## Key Concepts

### DhanHQ API Architecture

DhanHQ provides REST APIs for historical data and WebSocket for live data. This phase uses REST only.

**Base URL:** `https://api.dhan.co`

**Authentication:**
- Header: `access-token: <DHAN_ACCESS_TOKEN>`
- Header: `client-id: <DHAN_CLIENT_ID>`

### Relevant DhanHQ Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/v2/instruments` | GET | Download full instrument master CSV |
| `/v2/marketdata/historical` | POST | Fetch historical candles |
| `/v2/marketdata/quote` | POST | Get current quote |
| `/v2/funds` | GET | Check fund limits |

### Instrument Discovery Flow

```
1. GET /v2/instruments → full instrument master (CSV)
2. Filter: exchange_segment == NSE_FNO
3. Filter: underlying_symbol == "NIFTY"
4. Filter: instrument_type == "FUT"
5. Filter: expiry >= July 2026 start
6. Filter: expiry <= July 2026 end
7. Result: NIFTY futures contract(s) for July
```

### Historical Data Request

```python
# POST /v2/marketdata/historical
{
    "security_id": "<contract_security_id>",
    "exchange_segment": "NSE_FNO",
    "instrument_type": "FUT",
    "from_date": "2026-07-01",
    "to_date": "2026-07-31",
    "interval": "1m"
}
```

**Response:** Array of OHLCV candles with timestamps.

### Rate Limits

DhanHQ imposes rate limits:
- 10 requests per second (varies by endpoint)
- Historical data may have paginated responses
- Instrument master update: once per day

### Data Normalization

Internal Candle schema (broker-independent):

```python
from dataclasses import dataclass
from datetime import datetime

@dataclass
class Candle:
    timestamp: datetime
    instrument: str       # "NIFTY_FUT"
    security_id: str      # Dhan's security_id
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_interest: int
    exchange: str         # "NSE_FNO"
    instrument_type: str  # "FUT"
    expiry: str           # "2026-07-31"
    lot_size: int
    tick_size: float
```

### Parquet Storage

```
data/raw/futures/NIFTY/2026-07/
├── contract_metadata.json
└── candles_1m.parquet
```

Parquet schema:
- Columns: timestamp, instrument, security_id, open, high, low, close, volume, open_interest
- Partitioning: by instrument and month
- Compression: snappy (default)

## Tech References

| Library | Usage | Notes |
|---------|-------|-------|
| `httpx` | HTTP client for DhanHQ REST API | Async-capable |
| `polars` | DataFrame → Parquet | Fast I/O |
| `pyarrow` | Parquet write engine | Schema enforcement |
| `pydantic` | Data validation for API responses | Type safety |

## Data Contracts

### Input
- DhanHQ credentials (env vars)
- Date range: July 2026
- Instrument: NIFTY Futures

### Output
- `candles_1m.parquet`: All 1-minute candles for July 2026
- `contract_metadata.json`: Contract details (security_id, expiry, lot_size, tick_size)

### Parquet Schema

| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime64[ns] | Candle open time (IST) |
| instrument | utf8 | "NIFTY_FUT" |
| security_id | utf8 | Dhan security ID |
| open | f64 | Open price |
| high | f64 | High price |
| low | f64 | Low price |
| close | f64 | Close price |
| volume | i64 | Volume |
| open_interest | i64 | Open interest |

## Dependencies

- Phase 00 (project foundation)
- DhanHQ account with API access
- `.env` with `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`

## Definition of Done

- [ ] DhanHQ authentication works
- [ ] NIFTY Futures contract correctly identified for July 2026
- [ ] July 2026 1-minute data downloaded
- [ ] Data saved as Parquet with correct schema
- [ ] Contract metadata saved as JSON
- [ ] No duplicate candles
- [ ] Timestamps are correct (IST, no gaps during trading hours)
- [ ] Reproducible: re-running download produces identical Parquet

## Open Questions

- Does Dhan provide tick-level data or only 1-minute candles?
- How are missing candles during halts handled?
- Should we store raw API response alongside normalized data?
- What's the max candles per request? Do we need chunking?
- Multiple July contracts (near-month vs far-month)?
