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

- [ ] Parameter grid search works
- [ ] Walk-forward validation implemented
- [ ] Regime analysis implemented
- [ ] Robustness metrics calculated
- [ ] Results stored with experiment IDs
- [ ] Report generated

## Open Questions

- How many walk-forward windows are sufficient?
- How to define "regime" without India VIX data?
- Should we use parallel processing for parameter search?
- How to handle overfitting detection?
