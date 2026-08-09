# Phase 08 — Advanced Research

## Goal

Add parameter search, walk-forward validation, and regime analysis to the research toolkit.

## What We're Building

The advanced research layer that goes beyond a single backtest: grid search over parameter space, walk-forward validation to avoid overfitting, and regime-aware analysis.

## Deliverables

- Parameter grid search tool
- Walk-forward validation engine
- Regime analysis (high/low volatility)
- Robustness report generation

## Key Concepts

### Parameter Search

Test combinations of parameters to find the best-performing set.

**Search space:**
```
Fast EMA:     [5, 7, 9, 12]
Slow EMA:     [15, 18, 21, 25]
Angle:        [20°, 25°, 30°, 35°, 40°]
Lookback:     [1, 2, 3, 5]
```

**Total combinations:** 4 × 4 × 5 × 4 = 320

**Important:** Parameter search uses only the training set (July 1-23), not the full dataset.

### Train / Validation / Test Split

```
July 2026
├──────────────────┬───────────┬───────────┤
│ Training         │ Validation│ Test      │
│                  │           │           │
│ July 1-23        │ July 24-27│ July 28-31│
└──────────────────┴───────────┴───────────┘
```

For a deterministic strategy, "training" = parameter calibration.

### Walk-Forward Validation

More reliable than selecting parameters using the full dataset.

```
Step 1: Train on July 1-15 → Test on July 16-20
Step 2: Train on July 1-20 → Test on July 21-25
Step 3: Train on July 1-25 → Test on July 26-31
```

Each step:
1. Optimize parameters on training window
2. Apply best params to unseen test window
3. Record out-of-sample performance

### Regime Analysis

Analyze strategy performance under different market conditions:

```
High volatility regime:
  - India VIX > 20
  - NIFTY daily range > 1.5%
  
Low volatility regime:
  - India VIX < 15
  - NIFTY daily range < 0.8%
```

### Robustness Metrics

```
- In-sample vs out-of-sample degradation
- Parameter sensitivity (how much does performance change with small param changes?)
- Win rate stability across regimes
- Drawdown consistency
- Profit factor stability
```

## Data Contracts

### Input
- Candle data (all timeframes)
- Signal engine (Phase 04)
- Backtester (Phase 05)

### Output
- `data/results/parameter_search_results.parquet`
- `data/results/walk_forward_results.parquet`
- `data/results/regime_analysis.json`
- `data/results/robustness_report.md`

## Dependencies

- Phase 05 (backtester)
- Phase 04 (strategy engine)

## Definition of Done

- [x] Parameter grid search works
- [x] Walk-forward validation implemented
- [x] Regime analysis implemented
- [x] Robustness metrics calculated
- [x] Results stored with experiment IDs
- [x] Report generated

## July 2026 Results (baseline run, 2026-08-09)

Tools: `quant/research/parameter_search.py`, `quant/research/walk_forward.py`,
`quant/research/regime.py`, `scripts/run_research.py`.
Outputs: `data/results/futures/NIFTY/2026-07/research/`
(`parameter_search_<tf>.parquet`, `walk_forward_<tf>.parquet`,
`regime_analysis.json`, `robustness_report.md`).

Grid (320 combos, training window Jul 1-23 only):

| Timeframe | Best params (fast/slow/angle/lookback) | Train net | PF | Positive combos | Median net |
|---|---|---|---|---|---|
| 1m | 5 / 18 / 25 / 5 | +32,272 | 2.90 | 58.1% | +2,860 |
| 5m | 7 / 21 / 35 / 5 | +26,791 | 4.23 | 45.6% | -659 |
| 15m | 7 / 18 / 40 / 3 | +17,959 | 2.57 | 21.6% | -11,897 |

Walk-forward (3 steps, out-of-sample windows): test nets of +6,181 / -1,121 /
+16,719 on 1m (2/7/1 trades), +2,096 / +18 / 0 on 5m (2/2/0 trades),
-399 / 0 / +4,633 on 15m (2/0/1 trades).

Regime analysis (B-config full month): July was a low-volatility month —
23 trading days split 1 high / 8 mid / 14 low. B-config lost money in low
regimes on 1m/5m (-18,672 / -7,178) but made +10,628 on 15m mid regime
(PF 1.75).

Observations:
- Best params are small fast EMA (5-7), mid slow EMA (18-21), permissive
  angle (25-40); the 320-grid best meaningfully beats default B-config on
  every timeframe (train set).
- Out-of-sample windows are extremely thin (0-2 trades); walk-forward is
  directionally informative but not statistically decisive on one month.
- Regime split is lopsided (no high-vol days in July); monthly regimes
  will be more interesting once multiple months exist.
- Runtime: full 1m grid = ~1-2 min, 5m/15m seconds each (single-process).
  Parallelization deferred (see open question).

## Open Questions

- ~~How many walk-forward windows are sufficient?~~ Settled on 3 anchored
  steps of 5 test days for one month (July 16-20 / 21-25 / 26-31).
- ~~How to define "regime" without India VIX data?~~ -> Realized daily range
  (high-low)/close: >1.5% high, <0.8% low, else mid.
- How to handle parameter search speed: parallel processing only if monthly
  grid runs get longer with new months.
- Overfitting detection: current signal = IS vs OOS degradation + median
  vs-best spread in one sweep, OS stability is per-window.
