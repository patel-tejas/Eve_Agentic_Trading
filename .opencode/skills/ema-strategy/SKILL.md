---
name: ema-strategy
description: >-
  Use when answering questions about the EMA 9/15 + angle strategy, its
  signal rules, variants, or when configuring generate_signal and
  run_backtest_signals parameters. Covers signal semantics, no-look-ahead
  guarantees, and the A/B/C variant definitions.
---

# EMA 9/15 + Angle Strategy (Phase 04)

## Strategy rules

- **BUY**: bullish crossover (fast EMA crosses above slow EMA) AND
  fast-EMA angle >= threshold (+30° default)
- **SELL**: bearish crossover (fast EMA crosses below slow EMA) AND
  fast-EMA angle <= threshold (-30° default)
- Anything else: **HOLD**

## Signal engine contract

- Indicators are recomputed by the engine from OHLCV — never trust
  indicator columns in inputs.
- Deterministic: same candles + same config → identical output.
- No look-ahead: at bar `t` only bars `<= t` are used. Crossover uses
  `t-1`; angle uses close of `t`.
- Seed window: the first `slow_ema - 1` bars carry no slow EMA and are
  always HOLD.

## Parameters (StrategyConfig)

| Field | Default | Notes |
|---|---|---|
| `fast_ema` | 9 | must be < `slow_ema` |
| `slow_ema` | 15 | |
| `angle_threshold` | 30.0 | degrees; applies to both sides |
| `angle_lookback` | 1 | bars used for slope |
| `signal_mode` | `crossover_and_angle` | `crossover` (angle gate off) / `crossover_and_angle` (B) / `crossover_angle_and_trend` (C: also requires close above slow EMA for BUY) |

## Variants

- **A** = `crossover` — most signals, worst cost drag.
- **B** = `crossover_and_angle` — the default strategy.
- **C** = `crossover_angle_and_trend` — trend filter on top of B.

## Signal output columns

`timestamp, signal_type (BUY/SELL/HOLD), crossover, ema_fast, ema_slow,
angle, candle_close` — one row per bar, HOLD rows included.

## Practical facts (July 2026 baseline)

- Non-HOLD counts: 1m → 3 BUY / 6 SELL; 5m → 6/5; 15m → 5/4 (B config).
- B == C on July because the trend filter never discriminated (price
  stayed above the slow EMA for all eligible crosses).
- Angle gate cuts most A-variant trades.