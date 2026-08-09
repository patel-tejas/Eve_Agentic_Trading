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

- [x] All three timeframes backtested
- [x] All three strategy variants (A, B, C) tested
- [x] Comparison table complete
- [x] Report generated with all sections
- [x] Experiment ID and config hash assigned
- [x] Results reproducible
- [x] No fabricated metrics

### July 2026 Baseline (2026-08-09)

`scripts/run_baseline.py --year 2026 --month 7` -> 9 experiments
(3 variants x 3 timeframes), EXP-2026-0001..0009.
Artifacts: `baseline_comparison.json`, `baseline_report.md`,
`baseline/trades_<EXP-ID>.parquet` under `data/results/futures/NIFTY/2026-07/`.

Net P&L matrix (slippage normal = 1 tick, costs india_futures_v1):

| Variant | 1m | 5m | 15m |
|---------|----|----|-----|
| A crossover only | -103,025 (268 tr) | -34,023 (44) | -15,794 (12) |
| B + angle 30 | -18,672 (2) | -20,225 (4) | **+5,737** (4) |
| C + trend filter | -18,672 (2) | -20,225 (4) | **+5,737** (4) |

Observations:

- Variant A over-trades on 1m (268 trades): every raw crossover is traded
  into an unprofitable noise regime; frictions compound. The angle filter
  prevents ~99% of 1m trades.
- **B == C in this sample**: the price-vs-slow-EMA trend condition never
  discriminates — every crossover that already passed the 30 deg angle gate
  had price on the correct side of the slow EMA. Trend filter is redundant
  for July (worth re-testing on more months).
- Only B/C on 15m end net positive (PF 1.35, Sharpe 0.95, maxDD 2.6%).
- Statistical caveats: 4 trades per positive cell — no significance. The
  comparison is a pipeline/behavior benchmark, not proof of edge.

## Open Questions (resolved)

- **Which variant is "the true baseline"?** B (EMA crossover + 30 deg angle)
  is the documented strategy minimum; A exists to quantify the filter's
  value, C to test the trend condition.
- **Multiple months?** Yes — the framework now accepts any processed month;
  multi-month evaluation lands with the research pipeline (phase 08).
- **Statistical significance?** Not claimable from 2-12 trades/month; treat
  all July numbers as descriptive. Optional resampling-based intervals in
  phase 08.
- **"Meaningful edge"?** Decision rule proposed: positive net P&L AND
  PF > 1.25 AND maxDD < 10% on a month as a first sieve.
