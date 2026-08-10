---
description: Use when running backtests, understanding the EMA crossover strategy, or interpreting signals and variants A/B/C.
---

# EMA 9/15 + Angle Strategy

## Signal rules

- **BUY**: bullish crossover (fast EMA crosses above slow EMA) AND fast-EMA angle >= threshold (+30° default)
- **SELL**: bearish crossover AND fast-EMA angle <= threshold (−30° default)
- Otherwise: **HOLD**

## Engine contract

- Deterministic: same candles + same config → identical output every time.
- No look-ahead: crossover uses bar t-1, angle uses close of t.
- First `slow_ema - 1` bars are always HOLD (seed window, no slow EMA yet).

## Parameters (StrategyConfig)

| Field | Default | Notes |
|---|---|---|
| `fast_ema` | 9 | must be < `slow_ema` |
| `slow_ema` | 15 | |
| `angle_threshold` | 30.0 | degrees, applies to both sides |
| `angle_lookback` | 1 | bars used for slope calculation |
| `signal_mode` | `crossover_and_angle` | see variants below |

## Variants

- **A** = `crossover` — crossover only, no angle gate (most signals)
- **B** = `crossover_and_angle` — default research strategy
- **C** = `crossover_angle_and_trend` — also requires close above slow EMA for BUY