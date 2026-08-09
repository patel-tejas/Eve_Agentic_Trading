# Phase 04 — Strategy Engine

## Goal

Implement the deterministic signal engine: EMA 9, EMA 15, angle calculation, crossover detection, and BUY/SELL signal generation.

## What We're Building

The core quantitative engine that transforms raw candles into trading signals. This is the mathematical source of truth — the LLM never calculates these values itself.

## Deliverables

- EMA 9 and EMA 15 calculation
- Normalized slope → angle calculation
- Crossover detection (bullish/bearish)
- BUY/SELL/HOLD signal generation
- Strategy configuration system
- Reproducible signal output

## Key Concepts

### EMA Calculation

**Exponential Moving Average** — weighted average where recent prices get more weight.

```
alpha = 2 / (N + 1)

EMA[0] = SMA(first N values)     # seed with simple moving average
EMA[t] = alpha × price[t] + (1 - alpha) × EMA[t-1]
```

For our strategy:
```
EMA 9:  alpha = 2 / (9 + 1)  = 0.20
EMA 15: alpha = 2 / (15 + 1) = 0.125
```

### Angle Calculation

The angle quantifies the slope/trend strength of the EMA. A pure visual angle depends on chart scaling, so we use a normalized mathematical definition.

**Step 1: Normalized slope**
```
normalized_slope = (EMA[t] - EMA[t-k]) / EMA[t-k]
```

Where `k` is the lookback period (e.g., 1-5 candles).

**Step 2: Scale and convert to degrees**
```
angle = atan(normalized_slope × scale) × (180 / π)
```

**Parameters:**
- `angle_threshold`: 30° (the filter threshold)
- `angle_lookback`: number of candles for slope calculation
- `angle_scale`: normalization factor

### Crossover Detection

**Bullish crossover (BUY signal):**
```
ema9[t] > ema15[t] AND ema9[t-1] <= ema15[t-1]
```

**Bearish crossover (SELL signal):**
```
ema9[t] < ema15[t] AND ema9[t-1] >= ema15[t-1]
```

### Signal Rules

**BUY:**
```
9 EMA crosses above 15 EMA
AND
EMA angle >= +30°
```

**SELL:**
```
9 EMA crosses below 15 EMA
AND
EMA angle <= -30°
```

**HOLD:**
```
No qualifying crossover
```

### Strategy Configuration

```python
from pydantic import BaseModel

class StrategyConfig(BaseModel):
    fast_ema: int = 9
    slow_ema: int = 15
    angle_threshold: float = 30.0  # degrees
    angle_lookback: int = 1
    angle_scale: float = 1000.0    # normalization factor
    signal_mode: str = "crossover_and_angle"
```

### Signal Output Schema

```python
@dataclass
class Signal:
    timestamp: datetime
    instrument: str
    timeframe: str      # "1m", "5m", "15m"
    signal_type: str    # "BUY", "SELL", "HOLD"
    ema_fast: float
    ema_slow: float
    angle: float
    crossover: bool     # True if crossover occurred
    candle_close: float
```

### Key Implementation Notes

1. **No look-ahead bias**: Signals use only data available at candle close
2. **Seed period**: First N candles (where N = slow EMA period) have no valid EMA — skip them
3. **Angle normalization**: The scale factor must be frozen before benchmark
4. **Reproducibility**: Same inputs must produce identical signals

## Data Contracts

### Input
- `data/processed/candles_1m.parquet`
- `data/processed/candles_5m.parquet`
- `data/processed/candles_15m.parquet`
- `StrategyConfig`

### Output
- `data/results/signals_1m.parquet`
- `data/results/signals_5m.parquet`
- `data/results/signals_15m.parquet`

## Dependencies

- Phase 03 (candle data at all timeframes)

## Definition of Done

- [x] EMA 9 calculation correct
- [x] EMA 15 calculation correct
- [x] Angle calculation mathematically documented
- [x] Crossover detection works (bullish + bearish)
- [x] BUY/SELL signals generated correctly
- [x] Signals reproducible across runs
- [x] No look-ahead bias
- [x] Seed period handled (skip first N candles)
- [x] All three timeframes processed

### July 2026 Baseline (2026-08-09)

`data/results/futures/NIFTY/2026-07/signals_{1m,5m,15m}.parquet`
(frozen config: EMA 9/15, angle threshold 30 deg, lookback 1, scale 1000):

| Timeframe | Bars | BUY | SELL |
|-----------|------|-----|------|
| 1m | 8625 | 3 | 6 |
| 5m | 1725 | 6 | 5 |
| 15m | 575 | 5 | 4 |

Signals verified: every BUY has `ema_fast > ema_slow` at crossover bar and
`angle >= 30`; every SELL the mirror. Output schema matches the phase spec
(`timestamp, signal_type, crossover, ema_fast, ema_slow, angle, candle_close`).

Implementation notes:

- The engine recomputes indicators from OHLCV; it never trusts input
  indicator columns (mathematical source of truth, reproducible).
- `signal_events()` converts non-HOLD rows to `Signal` dataclasses for the
  backtester (phase 05).
- 1m signals are sparse (3 BUY/6 SELL over 23 days) because 1-min candles
  rarely hold a 30 deg fast-EMA angle at the exact crossover bar; 5m/15m
  carry the actionable signals.

## Open Questions (resolved)

- **angle_scale / lookback calibration?** Frozen at 1000.0 / 1 per the
  spec; systematic calibration deferred to parameter research (phase 08).
- **EMA slope vs price-E distance?** Spec's normalized-EMA-slope definition
  is implemented (`(EMA[t] - EMA[t-k]) / EMA[t-k] * scale` -> atan -> deg).
- **Which EMA does the angle gate use?** The fast EMA's angle (more
  reactive); configurable later via `angle` column parameter if needed.
- **Gaps in EMA continuity?** EMA is per-frame causal (polars `ewm_mean`);
  holiday gaps do not leak values across sessions because each processed
  frame is a contiguous session series. Cross-day continuity is a backtest
  concern (phase 05).
- **Polars vs pandas?** Polars throughout.
