# Phase 06 — Baseline Results

## Goal

Run the 9/15 EMA + ±30° angle strategy on 1m, 5m, and 15m timeframes for July 2026, compare results, and produce a baseline comparison report.

## What We're Building

The first actual research output: a side-by-side comparison of the same strategy across three timeframes, establishing whether the strategy has an edge and which timeframe performs best.

## Deliverables

- Backtest results for 1m, 5m, 15m timeframes
- Comparison table with all key metrics
- Baseline report documenting assumptions, results, and observations
- Reproducible experiment (ID, config hash, dataset version)

## Key Concepts

### Baseline Configuration

```
Strategy:     EMA 9 / EMA 15
Filter:       Angle ±30°
Entry:        Crossover + angle confirmation
Exit:         Opposite crossover
Execution:    Next candle open
Costs:        India futures v1
Slippage:     Normal (configurable)
Period:       July 2026
Instrument:   NIFTY Futures
```

### Three Baseline Experiments

#### Strategy A — EMA Crossover Only
```
BUY: 9 EMA crosses above 15 EMA
SELL: 9 EMA crosses below 15 EMA
No angle filter
```

#### Strategy B — EMA + Angle Filter
```
BUY: 9 EMA crosses above 15 EMA AND angle >= +30°
SELL: 9 EMA crosses below 15 EMA AND angle <= -30°
```

#### Strategy C — EMA + Angle + Trend Filter
```
BUY: 9 EMA > 15 EMA AND angle >= 30° AND price > 15 EMA
SELL: 9 EMA < 15 EMA AND angle <= -30° AND price < 15 EMA
```

### Comparison Table

| Metric | 1m | 5m | 15m |
|--------|----|----|-----|
| Total trades | - | - | - |
| Win rate | - | - | - |
| Gross P&L | - | - | - |
| Net P&L | - | - | - |
| Profit factor | - | - | - |
| Max drawdown | - | - | - |
| Sharpe ratio | - | - | - |
| Sortino ratio | - | - | - |
| Avg trade | - | - | - |
| Avg holding time | - | - | - |

### Experiment Reproducibility

Each experiment gets:
```json
{
  "experiment_id": "EXP-2026-0001",
  "config_hash": "sha256:...",
  "dataset_version": "nifty_futures_july_2026_v1",
  "strategy_version": "ema_9_15_angle_v1",
  "cost_model_version": "india_futures_v1",
  "engine_version": "0.1.0"
}
```

### Report Structure

```
1. Dataset
   - Instrument
   - Period
   - Timeframe

2. Strategy
   - EMA settings
   - Angle definition
   - Entry rules
   - Exit rules

3. Execution Assumptions
   - Transaction costs
   - Slippage

4. Performance
   - P&L
   - Win rate
   - Profit factor
   - Drawdown
   - Sharpe/Sortino

5. Observations
   - Which timeframe performed best
   - Failure cases
   - Potential improvements

6. Assumptions vs Hypotheses
   - What was measured vs what was assumed
```

## Data Contracts

### Input
- `data/results/trades_{1m,5m,15m}.parquet`
- `data/results/metrics_{1m,5m,15m}.json`

### Output
- `data/results/baseline_comparison.json`
- `data/results/baseline_report.md`

## Dependencies

- Phase 05 (backtester)
- Phase 04 (strategy engine)

## Definition of Done

- [ ] All three timeframes backtested
- [ ] All three strategy variants (A, B, C) tested
- [ ] Comparison table complete
- [ ] Report generated with all sections
- [ ] Experiment ID and config hash assigned
- [ ] Results reproducible
- [ ] No fabricated metrics

## Open Questions

- Which strategy variant is the "true baseline" (A, B, or C)?
- Should we test across multiple months before drawing conclusions?
- How to handle statistical significance with small sample sizes?
- What constitutes "meaningful edge" — Sharpe > 1? Positive net P&L?
