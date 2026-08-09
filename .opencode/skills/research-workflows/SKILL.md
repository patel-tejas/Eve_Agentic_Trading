---
name: research-workflows
description: >-
  Use to run or explain advanced research: parameter_grid_search grids,
  train/validation/test splits, walk-forward validation, regime analysis,
  and robustness reports. Trigger keywords: parameter search, grid search,
  walk-forward, out-of-sample, overfitting, regime, hyperparameter,tune.
---

# Research Workflows (Phase 08)

## Golden rule: calibration never touches test data

- **Training** = first 23 days of the month (default train split).
- **Validation** = days 24–27. **Test** = days 28–31.
- `parameter_search` runs on the **training window only**. Its top net P&L
  is in-sample; never present it as expected performance.

## Parameter search

- Default grid: fast EMA [5,7,9,12] × slow [15,18,21,25] × angle
  [20,25,30,35,40] × lookback [1,2,3,5] = 320 combos (fast < slow enforced).
- Result rows carry `RE-####` experiment IDs; sorted by net P&L.
- Summary stats to quote: `positive_share`, `median_net_pnl`, best combo.
- 1m on a full month is the slowest (~1-2 min); prefer 5m/15m for quick
  checks or narrow the grid.

## Walk-forward (the anti-overfitting check)

Three anchored steps (5-day test windows):

1. Train 1–15 → Test 16–20
2. Train 1–20 → Test 21–25
3. Train 1–25 → Test 26–31

Each step: grid-search on train ONLY → apply best params to the unseen
test window → record `test_net_pnl`. Quote OOS numbers, not train numbers.

## Regime analysis

- Regimes derived from realized daily range
  `(day_high − day_low) / day_close` (no VIX feed needed):
  - **high** > 1.5%  ·  **mid** 0.8–1.5%  ·  **low** < 0.8%
- July 2026: 23 days → 1 high / 8 mid / 14 low (a low-vol month).
- Trade results are attributed by entry date.

## Robustness report

- `data/results/futures/NIFTY/<YYYY-MM>/research/robustness_report.md`
- Contains splits, grid stats, walk-forward table, regime table.
- Overfitting signals: train net ≫ OOS net, or best combo flips between
  walk-forward steps.